"""実データ・APIを使わずにViewerを表示する公開用デモ。"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
import queue
import struct
import sys
import tempfile
import tkinter as tk
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gentrace.config import AppConfig
from gentrace.database import Database
from gentrace.gui import GenTraceGui


def capture_client(root: tk.Tk, target: Path) -> None:
    """デモウィンドウだけをPNG化する（デスクトップ全体は取得しない）。"""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC,ctypes.c_int,ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC,wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.GetDIBits.argtypes = [wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    hwnd = user32.GetAncestor(root.winfo_id(), 2)
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd,ctypes.byref(rect))
    width,height = rect.right,rect.bottom
    dc = user32.GetDC(hwnd)
    memory = gdi32.CreateCompatibleDC(dc)
    bitmap = gdi32.CreateCompatibleBitmap(dc,width,height)
    old = gdi32.SelectObject(memory,bitmap)
    try:
        if not user32.PrintWindow(hwnd,memory,1):
            raise OSError("デモ画面をキャプチャできません。")
        info = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,width*height*4,0,0,0,0))
        pixels = ctypes.create_string_buffer(width*height*4)
        gdi32.SelectObject(memory,old)
        if gdi32.GetDIBits(memory,bitmap,0,height,pixels,info,0) != height:
            raise OSError("デモ画面の画素を取得できません。")
        raw = pixels.raw
        scanlines = bytearray()
        for y in range(height):
            scanlines.append(0)
            row = raw[y*width*4:(y+1)*width*4]
            rgb = bytearray(width*3)
            rgb[0::3],rgb[1::3],rgb[2::3] = row[2::4],row[1::4],row[0::4]
            scanlines.extend(rgb)
        def chunk(kind,payload):
            return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xFFFFFFFF)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scanlines))+chunk(b'IEND',b''))
    finally:
        gdi32.SelectObject(memory,old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(hwnd,dc)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,help='Windowsで安全なデモ画面2枚を保存して終了')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='gentrace-demo-') as directory:
        temp=Path(directory)
        config=AppConfig(temp,temp,temp/'settings.json',temp,temp,'127.0.0.1',8188,(),0)
        db=Database(config.database_path)
        db.initialize()
        base=int(datetime(2026,1,1,3,tzinfo=timezone.utc).timestamp()*1000)
        statuses=['completed','failed','cancelled','imported']
        for i,status in enumerate(statuses):
            job=f'demo-{i+1:03}'
            started=base+i*60000
            params={'model_name':f'demo-model-{i+1}.safetensors','lora_names':'demo-style.safetensors' if i==0 else '', 'width':768,'height':768,'sampler':'euler','scheduler':'normal','steps':20+i*5,'cfg':6.5,'seed':100+i}
            db.upsert_job(job,status,started_at_utc=None if status=='imported' else started,ended_at_utc=None if status=='imported' else started+12000,parameters=params,backend='image_metadata' if status=='imported' else 'stability_matrix')
            if i in (0,3):
                db.add_output(job,Path(f'C:/demo/output/demo-{i+1:03}.png'),base,params)
            if i==0:
                for n,value in enumerate((15,42,65,78,82,72,50,24)):
                    db.add_gpu_sample(job,started+n*1000,value)
                db.update_gpu_summary(job)
        # DB内の記録日時も固定し、実際の利用時刻を画面に残さない。
        with db.session() as c:
            c.execute('UPDATE jobs SET captured_at_utc=?,updated_at_utc=?',(base,base))
        root=tk.Tk()
        gui=GenTraceGui(root,config,db,queue.Queue(),root.destroy)
        root.title('GenTrace Demo - synthetic data only')
        root.geometry('1480x920')
        def select(job):
            gui.refresh()
            gui.tree.selection_set(job)
            gui._show_selection()
            gui.footer_var.set('DEMO: synthetic records / temporary SQLite / no real images or prompts')
            gui.connection_var.set('DEMO: API未接続 / すべて架空の生成履歴')
            gui.gpu_var.set('DEMO: GPU値は説明用の架空値')
            root.update()
        select('demo-004')
        if args.capture:
            def capture():
                select('demo-004')
                capture_client(root,args.capture/'viewer-demo.png')
                select('demo-001')
                capture_client(root,args.capture/'gpu-demo.png')
                root.destroy()
            root.after(250,capture)
        root.mainloop()


if __name__=='__main__':
    main()
