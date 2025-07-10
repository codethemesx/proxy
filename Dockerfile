# Usa imagem oficial Python 3.10 slim (menos pesada)
FROM python:3.10-slim

# Instalar FFmpeg e dependências necessárias
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean && rm -rf /var/lib/apt/lists/*

# Define diretório de trabalho
WORKDIR /app

# Copia requirements.txt e instala dependências Python
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código para dentro do container
COPY . .

# Expõe porta que o Flask usará
EXPOSE 8000

# Comando para rodar a aplicação
CMD ["python", "app.py"]
