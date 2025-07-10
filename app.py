from flask import Flask, request, Response, render_template
import requests
import subprocess
import threading
from urllib.parse import urljoin

app = Flask(__name__)
session = requests.Session()

URL_BASES_JSON = 'https://raw.githubusercontent.com/codethemesx/proxy/refs/heads/main/bases.json'
URL_REFERERS_JSON = 'https://raw.githubusercontent.com/codethemesx/proxy/refs/heads/main/referers.json'

# Armazena processos FFmpeg ativos
processos_ffmpeg = {}
lock = threading.Lock()

# Função para carregar JSON remoto
def carregar_json_remoto(url):
    try:
        r = session.get(url, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Erro ao carregar JSON de {url}: {e}")
        return []

# Buscar valor de entrada a partir da saída
def obter_entrada_por_saida(lista, saida):
    for item in lista:
        if item["saida"] == saida:
            return item["entrada"]
    return None

@app.route('/')
def painel():
    return render_template('index.html')

@app.route('/<saida_base>/<saida_referer>/<path:path>')
def proxy_masked(saida_base, saida_referer, path):
    bases = carregar_json_remoto(URL_BASES_JSON)
    referers = carregar_json_remoto(URL_REFERERS_JSON)

    base_remota = obter_entrada_por_saida(bases, saida_base)
    referer = obter_entrada_por_saida(referers, saida_referer)

    if not base_remota or not referer:
        return "Base remota ou referer não encontrados no JSON.", 400

    remote_url = urljoin(base_remota + '/', path)

    headers = {
        'Referer': referer,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
    }

    try:
        is_playlist = remote_url.endswith('.m3u8')
        resp = session.get(remote_url, headers=headers, stream=not is_playlist, timeout=10)
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', '').lower()

        if is_playlist or 'application/vnd.apple.mpegurl' in content_type:
            lines = resp.text.splitlines()
            new_lines = []
            base_url = request.host_url.rstrip('/')
            for line in lines:
                line = line.strip()
                if line == '' or line.startswith('#'):
                    new_lines.append(line)
                else:
                    abs_url = urljoin(remote_url, line)
                    if abs_url.startswith(base_remota):
                        relative_path = abs_url.replace(base_remota + '/', '')
                        proxied_url = f"{base_url}/{saida_base}/{saida_referer}/{relative_path}"
                        new_lines.append(proxied_url)
                    else:
                        new_lines.append(abs_url)

            data = "\n".join(new_lines)
            response = Response(data)
            response.headers['Content-Type'] = 'application/vnd.apple.mpegurl'
        else:
            def generate():
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            response = Response(generate())
            response.headers['Content-Type'] = content_type if content_type else 'video/MP2T'

        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = '*'
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Connection'] = 'keep-alive'
        if 'Content-Disposition' in response.headers:
            del response.headers['Content-Disposition']

        return response

    except Exception as e:
        return f"Erro no proxy: {e}", 500

@app.route('/<saida_base>/<saida_referer>/<canal>/live/start')
def iniciar_transmissao(saida_base, saida_referer, canal):
    servidor = request.args.get('rtmps')
    chave = request.args.get('token')

    if not servidor or not chave:
        return "Parâmetros 'rtmps' e 'token' são obrigatórios.", 400

    stream_key = f"{servidor}/{chave}"
    path_id = f"{saida_base}/{saida_referer}/{canal}/live"

    with lock:
        if path_id in processos_ffmpeg:
            return "Transmissão já está em andamento.", 200

        bases = carregar_json_remoto(URL_BASES_JSON)
        referers = carregar_json_remoto(URL_REFERERS_JSON)
        base_remota = obter_entrada_por_saida(bases, saida_base)
        referer = obter_entrada_por_saida(referers, saida_referer)

        if not base_remota or not referer:
            return "Base ou Referer inválido.", 400

        url_m3u8 = f"{base_remota}/{canal}/live.m3u8"

        comando = [
            "ffmpeg",
            "-re", "-i", url_m3u8,
            "-c:v", "copy",
            "-c:a", "aac",
            "-f", "flv",
            stream_key
        ]

        try:
            processo = subprocess.Popen(comando)
            processos_ffmpeg[path_id] = processo
            return f"Transmissão iniciada para {path_id}.", 200
        except Exception as e:
            return f"Erro ao iniciar FFmpeg: {e}", 500

@app.route('/<saida_base>/<saida_referer>/<canal>/live/exit')
def parar_transmissao(saida_base, saida_referer, canal):
    path_id = f"{saida_base}/{saida_referer}/{canal}/live"
    with lock:
        processo = processos_ffmpeg.get(path_id)
        if processo:
            processo.terminate()
            processo.wait()
            del processos_ffmpeg[path_id]
            return f"Transmissão finalizada para {path_id}.", 200
        else:
            return "Nenhuma transmissão ativa encontrada.", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
