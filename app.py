from flask import Flask, request, Response, render_template
import requests
import subprocess
import threading
from urllib.parse import urljoin
import json

app = Flask(__name__)
session = requests.Session()

URL_BASES_JSON = 'https://raw.githubusercontent.com/codethemesx/proxy/main/bases.json'
URL_REFERERS_JSON = 'https://raw.githubusercontent.com/codethemesx/proxy/main/referers.json'

processos_ffmpeg = {}

def carregar_json_remoto(url):
    try:
        r = session.get(url, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Erro ao carregar JSON de {url}: {e}")
        return []

def obter_entrada_por_saida(lista, saida):
    for item in lista:
        if item["saida"] == saida:
            return item["entrada"]
    return None

@app.route('/')
def painel():
    return render_template("index.html")

@app.route('/<saida_base>/<saida_referer>/<path:canal>/live/start')
def iniciar_live(saida_base, saida_referer, canal):
    rtmps = request.args.get("rtmps")
    token = request.args.get("token")

    if not rtmps or not token:
        return "Parâmetros 'rtmps' e 'token' são obrigatórios.", 400

    stream_key = f"{rtmps}{token}"

    bases = carregar_json_remoto(URL_BASES_JSON)
    referers = carregar_json_remoto(URL_REFERERS_JSON)

    base_remota = obter_entrada_por_saida(bases, saida_base)
    referer = obter_entrada_por_saida(referers, saida_referer)

    if not base_remota or not referer:
        return "Base remota ou referer não encontrados.", 400

    canal_id = f"{saida_base}_{saida_referer}_{canal}"

    if canal_id in processos_ffmpeg:
        return f"Live já está em execução para '{canal_id}'.", 200

    url_m3u8 = f"{base_remota}/{canal}"
    headers_ffmpeg = f"Referer: {referer}\r\nUser-Agent: Mozilla/5.0\r\n"

    comando = [
        "ffmpeg",
        "-re",
        "-headers", headers_ffmpeg,
        "-i", url_m3u8,
        "-c:v", "copy",
        "-c:a", "aac",
        "-f", "flv",
        stream_key
    ]

    def iniciar_ffmpeg():
        try:
            processo = subprocess.Popen(comando)
            processos_ffmpeg[canal_id] = processo
            processo.wait()
            del processos_ffmpeg[canal_id]
        except Exception as e:
            print(f"Erro ao iniciar FFmpeg: {e}")

    threading.Thread(target=iniciar_ffmpeg, daemon=True).start()

    return f"Live iniciada para '{canal_id}'", 200

@app.route('/<saida_base>/<saida_referer>/<path:canal>/live/exit')
def parar_live(saida_base, saida_referer, canal):
    canal_id = f"{saida_base}_{saida_referer}_{canal}"
    processo = processos_ffmpeg.get(canal_id)

    if not processo:
        return f"Nenhuma live em execução para '{canal_id}'.", 404

    processo.terminate()
    del processos_ffmpeg[canal_id]
    return f"Live encerrada para '{canal_id}'", 200

@app.route('/<saida_base>/<saida_referer>/<path:path>')
def proxy_m3u8(saida_base, saida_referer, path):
    bases = carregar_json_remoto(URL_BASES_JSON)
    referers = carregar_json_remoto(URL_REFERERS_JSON)

    base_remota = obter_entrada_por_saida(bases, saida_base)
    referer = obter_entrada_por_saida(referers, saida_referer)

    if not base_remota or not referer:
        return "Base ou referer inválido.", 400

    remote_url = urljoin(base_remota + '/', path)
    is_playlist = remote_url.endswith('.m3u8')

    headers = {
        'Referer': referer,
        'User-Agent': 'Mozilla/5.0',
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
    }

    try:
        resp = session.get(remote_url, headers=headers, stream=not is_playlist, timeout=10)
        resp.raise_for_status()

        if is_playlist or 'application/vnd.apple.mpegurl' in resp.headers.get('Content-Type', ''):
            playlist_text = resp.text
            lines = playlist_text.splitlines()
            new_lines = []
            base_url = request.host_url.rstrip('/')

            for line in lines:
                line_strip = line.strip()
                if line_strip == '' or line_strip.startswith('#'):
                    new_lines.append(line_strip)
                else:
                    abs_url = urljoin(remote_url, line_strip)
                    if abs_url.startswith(base_remota):
                        relative_path = abs_url.replace(base_remota + '/', '')
                        proxied_url = f"{base_url}/{saida_base}/{saida_referer}/{relative_path}"
                        new_lines.append(proxied_url)
                    else:
                        new_lines.append(abs_url)

            data = "\n".join(new_lines)
            response = Response(data, content_type='application/vnd.apple.mpegurl')
        else:
            def generate():
                for chunk in resp.iter_content(chunk_size=8192):
                    yield chunk
            response = Response(generate(), content_type=resp.headers.get('Content-Type', 'video/MP2T'))

        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    except Exception as e:
        return f"Erro no proxy: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
