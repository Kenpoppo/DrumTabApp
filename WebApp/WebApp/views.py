from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import os
import sys
import json
from fpdf import FPDF

# プロジェクトのルートディレクトリをPythonパスに追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 絶対インポートに変更
from tab_generator import generate_tab as generate_guitar_tab, generate_tab as generate_bass_tab
from drum_analyzer import analyze_drum

# アップロードされたファイルを保存するディレクトリ
UPLOAD_DIR = 'uploads'

def index(request):
    return render(request, 'index.html')

@csrf_exempt
def upload_file(request):
    if request.method == 'POST':
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'ファイルがアップロードされていません'}, status=400)
        
        file = request.FILES['file']
        file_path = os.path.join(UPLOAD_DIR, file.name)
        
        # アップロードディレクトリが存在しない場合は作成
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)
        
        return JsonResponse({'message': 'ファイルがアップロードされました', 'file_path': file_path})

@csrf_exempt
def generate_tab(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        file_path = data.get('file_path')
        tab_type = data.get('type')  # 'guitar', 'bass', or 'drum'
        
        if not file_path or not os.path.exists(file_path):
            return JsonResponse({'error': 'ファイルが見つかりません'}, status=400)
        
        try:
            if tab_type == 'guitar':
                result = generate_guitar_tab(file_path)
            elif tab_type == 'bass':
                result = generate_bass_tab(file_path)
            elif tab_type == 'drum':
                result = analyze_drum(file_path)
            else:
                return JsonResponse({'error': '無効なTABタイプです'}, status=400)
            
            return JsonResponse({'result': result})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def export_pdf(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        tab_content = data.get('content')
        
        if not tab_content:
            return JsonResponse({'error': 'TABコンテンツがありません'}, status=400)
        
        try:
            pdf = FPDF()
            pdf.add_page()
            
            # Windows環境用のフォント設定
            pdf.set_font('Courier', '', 12)  # モノスペースフォントを使用
            
            # 絵文字を削除
            import re
            clean_text = re.sub(r'[^\x00-\x7F]+', '', tab_content)
            
            # 行間を調整してTAB譜を見やすく
            line_height = 6  # 行の高さを設定
            for line in clean_text.split("\n"):
                pdf.multi_cell(0, line_height, line)
            
            pdf_path = os.path.join(UPLOAD_DIR, 'tab.pdf')
            pdf.output(pdf_path)
            
            # PDFファイルへのURLを返す
            return JsonResponse({'pdf_path': pdf_path})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500) 