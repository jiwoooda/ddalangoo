import streamlit as st
import google.generativeai as genai
import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np
import threading
import time
import datetime

# --- 설정 ---
API_KEY = "입력한 API 키" 
genai.configure(api_key=API_KEY)
STT_MODEL_NAME = 'models/gemini-3-flash-preview'

def terminal_log(message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

# --- 스레드에서 공유할 전역 상태 객체 ---
class RecordingState:
    def __init__(self):
        self.is_recording = False
        self.buffer = []

# 앱이 실행될 때마다 초기화되지 않도록 세션에 저장
if "rec_state" not in st.session_state:
    st.session_state.rec_state = RecordingState()
if "log" not in st.session_state:
    st.session_state.log = "준비 완료"

# --- 백그라운드 녹음 함수 ---
def record_thread(state):
    """
    st.session_state를 직접 참조하지 않고 
    인자로 받은 state 객체를 사용하여 Context 에러를 방지합니다.
    """
    fs = 44100
    try:
        with sd.InputStream(samplerate=fs, channels=1, dtype='float32') as stream:
            terminal_log("스레드: 마이크 스트림 활성화")
            while state.is_recording:
                data, _ = stream.read(int(fs * 0.1))
                state.buffer.append(data)
        terminal_log("스레드: 루프 종료")
    except Exception as e:
        print(f"스레드 내부 에러: {e}")

# --- UI 섹션 ---
st.set_page_config(page_title="Gemini Threaded STT", layout="centered")
st.title("🚀 고성능 무제한 녹음 STT")

st.subheader("마이크 제어")
col1, col2 = st.columns(2)

state = st.session_state.rec_state

# 녹음 시작 버튼
if col1.button("🎙️ 녹음 시작", use_container_width=True, disabled=state.is_recording):
    state.is_recording = True
    state.buffer = [] # 버퍼 초기화
    
    # state 객체를 인자로 넘겨서 세션 컨텍스트 문제를 회피
    t = threading.Thread(target=record_thread, args=(state,), daemon=True)
    t.start()
    
    terminal_log("STT: 백그라운드 스레드 시작")
    st.rerun()

# 녹음 종료 버튼
if col2.button("⏹️ 녹음 종료", use_container_width=True, disabled=not state.is_recording):
    state.is_recording = False # 스레드 루프 중단
    terminal_log("STT: 녹음 중지 요청")
    
    with st.spinner("음성 파일 분석 중..."):
        # 스레드가 루프를 빠져나올 때까지 잠시 대기
        time.sleep(0.7) 
        
        if state.buffer:
            terminal_log(f"STT: 데이터 수집됨 (조각 개수: {len(state.buffer)})")
            full_audio = np.concatenate(state.buffer, axis=0)
            write('input_audio.wav', 44100, full_audio)

            # Gemini 분석
            audio_file = genai.upload_file(path='input_audio.wav')
            while audio_file.state.name == "PROCESSING":
                time.sleep(0.5)
                audio_file = genai.get_file(audio_file.name)
            
            model_stt = genai.GenerativeModel(STT_MODEL_NAME)
            response = model_stt.generate_content([audio_file, "이 음성을 한글 텍스트로 변환해줘."])
            
            terminal_log(f"STT: 결과 -> {response.text}")
            st.session_state.log = f"인식 결과: {response.text}"
        else:
            terminal_log("STT: 버퍼가 비어있음 (녹음 실패)")
            st.error("녹음된 데이터가 없습니다.")
        
    st.rerun()

if state.is_recording:
    st.success("🎤 녹음 중입니다... (스레드 안전 모드)")

st.divider()
st.text_area("인식 로그", value=st.session_state.log, height=150)