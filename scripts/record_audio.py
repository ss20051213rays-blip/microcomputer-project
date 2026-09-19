import sys
import os
import argparse

try:
    import sounddevice as sd
    import soundfile as sf
except ImportError:
    print("Error: sounddevice or soundfile not installed. Run: pip install sounddevice soundfile")
    sys.exit(1)

# 加入项目根目录
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.config import load_config

def main():
    parser = argparse.ArgumentParser(description="双麦克风阵列录音测试")
    parser.add_argument("--list", action="store_true", help="列出所有音频设备并退出")
    parser.add_argument("-d", "--duration", type=int, default=3, help="录音时长(秒)")
    parser.add_argument("-o", "--output", default="data/sample.wav", help="输出 WAV 文件路径")
    args = parser.parse_args()

    if args.list:
        print(sd.query_devices())
        sys.exit(0)
        
    config = load_config("configs/default.yaml")['audio']
    fs = config['sample_rate']
    channels = config['channels']
    
    print(f"[*] 准备录制 {args.duration} 秒音频 (采样率 {fs}Hz, {channels} 通道)...")
    
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    try:
        recording = sd.rec(int(args.duration * fs), samplerate=fs, channels=channels, dtype='int16')
        print("[*] 正在录音... (请拍手或发出声音)")
        sd.wait()
        sf.write(args.output, recording, fs)
        print(f"[+] 录音完成，已保存至 {args.output}")
        print("请在电脑上打开该 WAV 验证左右声道是否有波形。")
    except Exception as e:
        print(f"[-] 录音失败: {e}")

if __name__ == "__main__":
    main()

