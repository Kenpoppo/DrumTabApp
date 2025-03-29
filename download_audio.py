import yt_dlp
from pydub import AudioSegment
import os

def download_audio(url, output_dir="downloads"):
    os.makedirs(output_dir, exist_ok=True)
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_dir}/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded_file = ydl.prepare_filename(info).replace('.webm', '.mp3')

    wav_file = downloaded_file.replace('.mp3', '.wav')
    sound = AudioSegment.from_mp3(downloaded_file)
    sound.export(wav_file, format="wav")

    print(f"ダウンロード完了: {wav_file}")
    return wav_file
if __name__ == "__main__":
    url = input("ダウンロードするYouTubeのURLを入力してください: ")
    if url:
        download_audio(url)
    else:
        print("URLが入力されていません。")
