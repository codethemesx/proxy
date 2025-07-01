from flask import Flask, request, Response
import requests
from urllib.parse import urljoin

app = Flask(__name__)
session = requests.Session()

# Domínio base remoto que você quer mascarar
REMOTE_BASE = "https://embmaxtv.online"

@app.route('/<path:path>')
def proxy_masked(path):
    referer = request.args.get('referer', 'https://embedcanaistv.com')  # Pode ajustar ou parametrizar

    # Monta a URL remota completa
    remote_url = urljoin(REMOTE_BASE + '/', path)

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

        if is_playlist or 'application/vnd.apple.mpegurl' in content_type or 'application/x-mpegurl' in content_type:
            playlist_text = resp.text
            lines = playlist_text.splitlines()
            new_lines = []

            # Base URL do proxy, para reescrever as URLs internas
            base_url = request.host_url.rstrip('/')

            for line in lines:
                line_strip = line.strip()
                if line_strip == '' or line_strip.startswith('#'):
                    new_lines.append(line_strip)
                else:
                    abs_url = urljoin(remote_url, line_strip)
                    # Reescreve as URLs internas da playlist para passar pelo seu proxy também
                    proxied_path = abs_url.replace(REMOTE_BASE, '')
                    proxied_url = f"{base_url}{proxied_path}?referer={referer}"
                    new_lines.append(proxied_url)

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

        if 'Content-Disposition' in response.headers:
            del response.headers['Content-Disposition']

        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = '*'
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Connection'] = 'keep-alive'

        return response

    except Exception as e:
        return f"Erro no proxy: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
