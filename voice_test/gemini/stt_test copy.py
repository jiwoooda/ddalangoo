import streamlit as st
import google.generativeai as genai
import sounddevice as sd
from scipy.io.wavfile import write
import os
import time
import datetime
import io
import wave

# --- 설정 ---
# 보안을 위해 API 키는 환경 변수나 별도 파일로 관리하는 것이 좋지만, 
# 현재 테스트를 위해 직접 입력하셨으므로 그대로 유지합니다. (유출 주의!)
API_KEY = "AIzaSyB0AecFe54BLROk2wJhDiVgxEYDDvpyPMI" 
genai.configure(api_key=API_KEY)

# 터미널 로깅 함수
def terminal_log(message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

# --- 모델 설정 ---
STT_MODEL_NAME = 'models/gemini-3-flash-preview' 

st.set_page_config(page_title="Gemini STT/TTS Assistant")
st.title("🎤 Gemini STT/TTS 워크스페이스")

if "log" not in st.session_state:
    st.session_state.log = "시스템 준비 완료."

# --- STT 기능 (음성 -> 텍스트) ---
st.subheader("1. STT (음성 인식)")
if st.button("🔴 녹음 시작 (5초)"):
    fs = 44100
    seconds = 5
    terminal_log("STT: 녹음 시작")
    st.info("녹음 중... 말씀하세요!")
    
    recording = sd.rec(int(seconds * fs), samplerate=fs, channels=1)
    sd.wait()
    write('input_audio.wav', fs, recording)
    terminal_log("STT: 녹음 완료, 파일 저장됨 (input_audio.wav)")
    
    st.success("녹음 완료! 분석 중...")
    
    audio_file = genai.upload_file(path='input_audio.wav')
    terminal_log(f"STT: 파일 업로드 중 (ID: {audio_file.name})")
    
    while audio_file.state.name == "PROCESSING":
        time.sleep(0.5)
        audio_file = genai.get_file(audio_file.name)
    
    terminal_log("STT: 파일 처리 완료 (ACTIVE)")

    model_stt = genai.GenerativeModel(STT_MODEL_NAME)
    response = model_stt.generate_content([audio_file, "이 음성을 한글 텍스트로 변환해줘."])
    
    terminal_log(f"STT: 결과 수신 -> {response.text}")
    st.session_state.log = f"인식된 텍스트: {response.text}"
    st.rerun() # 로그 업데이트를 위해 화면 갱신


# --- 로그 출력 ---
st.divider()
st.text_area("Activity Log", value=st.session_state.log, height=100)