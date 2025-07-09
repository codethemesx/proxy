from flask import Flask, request, Response
import requests
from urllib.parse import urljoin
import json
import yt_dlp

app = Flask(__name__)
session = requests.Session()

URL_BASES_JSON = 'https://raw.githubusercontent.com/codethemesx/proxy/refs/heads/main/bases.json'
URL_REFERERS_JSON = 'https://raw.githubusercontent.com/codethemesx/proxy/refs/heads/main/referers.json'

# Obter lives do canal (retorna lista de dicionarios com id, titulo e m3u8)
def obter_lives_do_canal(canal_url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        resp = session.get(canal_url, headers=headers, timeout=5)
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/watch" in href and "live" in href:
                links.add("https://www.youtube.com" + href.split("&")[0])
        lives = []
        for link in links:
            ydl_opts = {'quiet': True, 'skip_download': True, 'forcejson': True, 'extract_flat': False}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(link, download=False)
                for fmt in info.get("formats", []):
                    if fmt.get("protocol") == "m3u8":
                        lives.append({
                            'id': info.get("id"),
                            'titulo': info.get("title"),
                            'm3u8': fmt.get("url")
                        })
                        break
        return lives
    except Exception as e:
        print(f"Erro ao buscar lives: {e}")
        return []

# Carregar JSON remoto
def carregar_json_remoto(url):
    try:
        r = session.get(url, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Erro ao carregar JSON de {url}: {e}")
        return []

# Buscar valor de entrada a partir da saida
def obter_entrada_por_saida(lista, saida):
    for item in lista:
        if item["saida"] == saida:
            return item["entrada"]
    return None

@app.route('/c/<int:numero_live>/<canal_id>.m3u8')
def proxy_canal(numero_live, canal_id):
    canal_url = f"https://www.youtube.com/channel/{canal_id}/live"
    lives = obter_lives_do_canal(canal_url)
    if numero_live > len(lives) or numero_live < 1:
        return f"Live {numero_live} não encontrada.", 404
    m3u8_url = lives[numero_live - 1]['m3u8']

    try:
        resp = session.get(m3u8_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        resp.raise_for_status()
        response = Response(resp.text)
        response.headers['Content-Type'] = 'application/vnd.apple.mpegurl'
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'no-cache'
        return response
    except Exception as e:
        return f"Erro ao acessar live: {e}", 500

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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36',
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
