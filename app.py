from flask import Flask, request, Response, render_template
import requests
import subprocess
import threading
from urllib.parse import urljoin
import json
import time

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
        print(f"[ERRO] Falha ao carregar JSON de {url}: {e}")
        return []

def obter_entrada_por_saida(lista, saida):
    for item in lista:
        if item["saida"] == saida:
            return item["entrada"]
    return None

def verificar_stream(url, headers):
    try:
        resp = session.head(url, headers=headers, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        print(f"[ERRO] HEAD falhou para {url}: {e}")
        return False

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
    canal_id = f"{saida_base}_{saida_referer}_{canal}"

    if canal_id in processos_ffmpeg:
        return f"Live já está rodando para '{canal_id}'", 200

    bases = carregar_json_remoto(URL_BASES_JSON)
    referers = carregar_json_remoto(URL_REFERERS_JSON)

    base_remota = obter_entrada_por_saida(bases, saida_base)
    referer = obter_entrada_por_saida(referers, saida_referer)
    if not base_remota or not referer:
        return "Base remota ou referer inválido.", 400

    url_m3u8 = f"{base_remota}/{canal}"
    headers_ffmpeg = f"Referer: {referer}\r\nUser-Agent: Mozilla/5.0\r\n"
    headers_requests = {
        'Referer': referer,
        'User-Agent': 'Mozilla/5.0'
    }

    # Verifica se o link HLS está acessível
    if not verificar_stream(url_m3u8, headers_requests):
        return f"[ERRO] Stream HLS inacessível: {url_m3u8}", 403

    comando = [
        "ffmpeg",
        "-re",
        "-headers", headers_ffmpeg,
        "-i", url_m3u8,
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c", "copy",
        "-f", "flv",
        stream_key
    ]

    def rodar_ffmpeg():
        while True:
            print(f"[INFO] Iniciando transmissão para {canal_id}")
            try:
                processo = subprocess.Popen(comando)
                processos_ffmpeg[canal_id] = processo
                processo.wait()
                print(f"[INFO] Transmissão encerrada para {canal_id}")
                if canal_id in processos_ffmpeg:
                    del processos_ffmpeg[canal_id]
                break
            except Exception as e:
                print(f"[ERRO] FFmpeg falhou: {e}")
                time.sleep(5)

    threading.Thread(target=rodar_ffmpeg, daemon=True).start()
    return f"Transmissão iniciada para '{canal_id}'", 200

@app.route('/<saida_base>/<saida_referer>/<path:canal>/live/exit')
def parar_live(saida_base, saida_referer, canal):
    canal_id = f"{saida_base}_{saida_referer}_{canal}"
    processo = processos_ffmpeg.get(canal_id)
    if not processo:
        return f"Nenhuma live rodando para '{canal_id}'", 404

    processo.terminate()
    del processos_ffmpeg[canal_id]
    return f"Transmissão encerrada para '{canal_id}'", 200

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
            return Response(data, content_type='application/vnd.apple.mpegurl')
        else:
            return Response(resp.iter_content(chunk_size=8192), content_type=resp.headers.get('Content-Type', 'video/MP2T'))

    except Exception as e:
        return f"Erro ao acessar o stream: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
