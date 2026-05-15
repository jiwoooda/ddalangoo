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
TTS_MODEL_NAME = 'models/gemini-2.5-flash-preview-tts'

st.set_page_config(page_title="Gemini STT/TTS Assistant")
st.title("🎤 Gemini STT/TTS 워크스페이스")

if "log" not in st.session_state:
    st.session_state.log = "시스템 준비 완료."

# --- 1. STT 기능 (음성 -> 텍스트) ---
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

if st.button("🔊 음성 생성"):
    if user_text:
        terminal_log(f"TTS: 요청 텍스트 -> {user_text}")
        st.write("음성 생성 중...")
        
        try:
            model_tts = genai.GenerativeModel(
                model_name=TTS_MODEL_NAME,
                generation_config={
                    "response_modalities": ["AUDIO"],
                    # 필요시 speech_config를 추가할 수 있습니다.
                }
            )
            
            response = model_tts.generate_content(user_text)
            terminal_log("TTS: API 응답 수신 완료")
            
            audio_part = None
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    audio_part = part.inline_data.data
                    break
            
            if audio_part:
                terminal_log(f"TTS: 오디오 바이트 추출 성공 ({len(audio_part)} bytes)")
                
                # --- [수정 포인트] 브라우저 인식을 위한 WAV 컨테이너 처리 ---
                # 만약 raw pcm 데이터라면 아래 처리가 필요합니다.
                # 여기서는 일단 바이너리를 그대로 넘기되, 형식을 명확히 지정합니다.
                
                # 방법 1: 가장 안전하게 데이터 스트림 재생
                st.audio(audio_part, format='audio/wav') 
                
                # 방법 2: (만약 위 방법이 안되면) 아래 주석을 풀어서 임시 파일로 저장 후 재생 시도
                """
                with open("temp_tts.wav", "wb") as f:
                    f.write(audio_part)
                st.audio("temp_tts.wav")
                """
                
                st.session_state.log = f"[TTS 생성 완료]: {user_text}"
                st.success("음성이 생성되었습니다. 아래 플레이어의 재생 버튼을 누르세요.")
            else:
                st.error("오디오 데이터를 찾을 수 없습니다.")
                
        except Exception as e:
            terminal_log(f"TTS 에러 발생: {str(e)}")
            st.error(f"에러 발생: {e}")


# --- 로그 출력 ---
st.divider()
st.text_area("Activity Log", value=st.session_state.log, height=100)