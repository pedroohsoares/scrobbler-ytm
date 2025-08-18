import pylast
import configparser
import json
from datetime import datetime, timezone
from ytmusicapi import YTMusic
import unicodedata
import re
import time
import os
# Importa as bibliotecas oficiais de autenticação do Google
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# --- FUNÇÃO DE LIMPEZA LOCAL (RÁPIDA) ---
def normalize_track_local(artist, title):
    def clean_text(text):
        text = text.lower()
        text = re.sub(r'[\(\[].*?[\)\]]', '', text)
        remove_words = ['official', 'video', 'audio', 'lyric', 'visualizer']
        for word in remove_words:
            text = re.sub(r'\b' + re.escape(word) + r'\b', '', text, flags=re.IGNORECASE)
        text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    return (clean_text(artist), clean_text(title))

# --- A LÓGICA DO SCRIPT ---
print("Iniciando o Sincronizador Autônomo...")

# Bloco 1: Carregando Configurações
try:
    config = configparser.ConfigParser()
    config.read('config.ini')
    LASTFM_API_KEY, LASTFM_API_SECRET, LASTFM_USERNAME, LASTFM_PASSWORD = config['lastfm']['api_key'], config['lastfm']['api_secret'], config['lastfm']['username'], config['lastfm']['password']
    LASTFM_PASSWORD_HASH = pylast.md5(LASTFM_PASSWORD)
    print("-> Credenciais do Last.fm carregadas.")
except Exception as e:
    exit(f"ERRO no config.ini: {e}")

# Bloco 2: Autenticação Autônoma com o Google
creds = None
TOKEN_PATH = 'oauth.json'
SCOPES = ['https://www.googleapis.com/auth/youtube']
if os.path.exists(TOKEN_PATH):
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        print("-> Token do Google expirado. Renovando automaticamente...")
        creds.refresh(Request())
    else:
        print("-> Realizando login inicial com o Google...")
        flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
        creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, 'w') as token_file:
        token_file.write(creds.to_json())
    print("-> Token do Google obtido/renovado e salvo com sucesso!")

# Bloco 3: Conectando com as plataformas
try:
    network = pylast.LastFMNetwork(api_key=LASTFM_API_KEY, api_secret=LASTFM_API_SECRET, username=LASTFM_USERNAME, password_hash=LASTFM_PASSWORD_HASH)
    print("-> Conectado ao Last.fm com sucesso!")
    
    # --- CORREÇÃO FINAL APLICADA AQUI ---
    # Montamos o cabeçalho manualmente a partir das credenciais,
    # que é o formato que a biblioteca entende.
    headers = {'Authorization': f'Bearer {creds.token}'}
    ytmusic = YTMusic(auth=headers)
    print("-> Conectado ao YouTube Music com sucesso!")
    
except Exception as e:
    exit(f"ERRO FATAL ao conectar: {e}")

# (O resto do script, blocos 4, 5 e 6, continua exatamente o mesmo)
# Bloco 4: Buscando Históricos
try:
    print("-> Buscando históricos...")
    ytm_history = ytmusic.get_history()
    user = network.get_user(LASTFM_USERNAME)
    lastfm_recent_tracks = user.get_recent_tracks(limit=500)
    print(f"-> Históricos de YTM ({len(ytm_history)}) e Last.fm ({len(lastfm_recent_tracks)}) recebidos.")
    lastfm_set = {normalize_track_local(track.track.artist.name, track.track.title) for track in lastfm_recent_tracks}
except Exception as e:
    exit(f"ERRO ao buscar históricos: {e}")

# Bloco 5: Comparando e encontrando as músicas novas
new_songs_to_scrobble = []
for song in ytm_history:
    artist = song.get('artists')[0]['name'] if song.get('artists') and song['artists'] else 'Artista Desconhecido'
    title = song['title']
    
    if normalize_track_local(artist, title) not in lastfm_set:
        new_songs_to_scrobble.append({'artist': artist, 'title': title})

new_songs_to_scrobble.reverse()

# Bloco 6: Lógica de Envio Híbrida (Automática vs. Manual)
if not new_songs_to_scrobble:
    print("\n-> Nenhuma música nova para enviar. Seu Last.fm está atualizado!")

# Se estiver rodando no GitHub Actions, envia direto
elif os.environ.get("CI") == "true":
    print(f"\n--- ENCONTRADAS {len(new_songs_to_scrobble)} MÚSICA(S) NOVA(S) ---")
    for song_data in new_songs_to_scrobble:
        print(f"  - {song_data['artist']} - {song_data['title']}")
    
    print("\n-> Rodando em modo automático. Iniciando o envio...")
    scrobbled_count = 0
    now_timestamp = int(datetime.now(timezone.utc).timestamp())
    for i, song_data in enumerate(new_songs_to_scrobble):
        try:
            network.scrobble(artist=song_data['artist'], title=song_data['title'], timestamp=now_timestamp - ((len(new_songs_to_scrobble) - 1 - i) * 240))
            print(f"   ✔ Scrobble enviado: {song_data['artist']} - {song_data['title']}")
            scrobbled_count += 1
        except pylast.PyLastError as e:
            print(f"   ✖ AVISO: Falha no scrobble para '{song_data['title']}': {e}")
    print(f"\n--- Processo concluído! {scrobbled_count} scrobbles novos foram enviados. ---")

# Se estiver rodando localmente, pergunta ao usuário
else:
    print(f"\n--- ENCONTRADAS {len(new_songs_to_scrobble)} MÚSICA(S) NOVA(S) ---")
    for song_data in new_songs_to_scrobble:
        print(f"  - {song_data['artist']} - {song_data['title']}")
    
    print("-" * 30)
    confirm = input("Você quer enviar esses scrobbles? (s/n): ").lower()
    
    if confirm == 's':
        print("\n--- Iniciando o envio de scrobbles ---")
        scrobbled_count = 0
        now_timestamp = int(datetime.now(timezone.utc).timestamp())
        for i, song_data in enumerate(new_songs_to_scrobble):
            try:
                network.scrobble(artist=song_data['artist'], title=song_data['title'], timestamp=now_timestamp - ((len(new_songs_to_scrobble) - 1 - i) * 240))
                print(f"   ✔ Scrobble enviado: {song_data['artist']} - {song_data['title']}")
                scrobbled_count += 1
            except pylast.PyLastError as e:
                print(f"   ✖ AVISO: Falha no scrobble para '{song_data['title']}': {e}")
        print(f"\n--- Processo concluído! {scrobbled_count} scrobbles novos foram enviados. ---")
    else:
        print("\n-> Envio cancelado pelo usuário.")
