# -*- coding: utf-8 -*-
# Multimodal Smart-Agri Copilot (Nongsaro Middle Category All Number Removal)

import base64
import json
import math
import datetime as dt
import os
from typing import List, Optional, Dict, Tuple
import xml.etree.ElementTree as ET # XML 파싱을 위해 추가
import urllib.parse # urllib.parse 모듈 임포트 추가
import re # 정규 표현식을 위해 추가

import requests
import streamlit as st
from PIL import Image

# --- Secrets 로드 (Streamlit 환경 및 로컬 테스트 환경 모두에서 동작하도록 개선) ---
def get_secret(key: str, default: str = "") -> str:
    """
    Streamlit 환경에서는 st.secrets에서, 그 외 환경에서는 .streamlit/secrets.toml에서 키를 로드합니다.
    """
    if hasattr(st, 'secrets'):
        raw_value = st.secrets.get(key, default)
    else:
        secrets_file_path = os.path.join(os.getcwd(), ".streamlit", "secrets.toml")
        secrets_data = {}
        try:
            with open(secrets_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip()
                        if v.startswith('"') and v.endswith('"'):
                            v = v[1:-1]
                        elif v.startswith("'") and v.endswith("'"):
                            v = v[1:-1]
                        secrets_data[k] = v
            raw_value = secrets_data.get(key, default)
        except FileNotFoundError:
            raw_value = default
        except Exception:
            raw_value = default
    
    if "%" in (raw_value or ""):
        return urllib.parse.unquote(raw_value)
    return raw_value

# ---------------------- Page / Secrets ----------------------
st.set_page_config(page_title="🌾 Smart-Agri Copilot", layout="wide")
st.title("🌾 다중모달 생성형 AI 코파일럿 ")
st.caption("텍스트+이미지로 물어보세요. 필요 시 툴(날씨·Plant.ID·농사로·스마트팜)을 자동 호출해 컨텍스트를 보강합니다.")

OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
PLANTID_API_KEY = get_secret("PLANTID_API_KEY")
NONGSARO_API_KEY = get_secret("NONGSARO_API_KEY")
SMARTFARM_KOREA_API_KEY = get_secret("SMARTFARM_KOREA_API_KEY")
AIHUB_API_KEY = get_secret("AIHUB_API_KEY")
KMA_API_KEY = get_secret("KMA_API_KEY")
RDA_WEATHER_API_KEY = get_secret("RDA_WEATHER_API_KEY")
RDAD_WEATHER_API_KEY = get_secret("RDAD_WEATHER_API_KEY")


# ---------------------- Helpers ----------------------
def img_to_data_url(img_bytes: bytes, mime="image/png") -> str:
    """바이트 이미지를 Base64 데이터 URL로 변환합니다."""
    return f"data:{mime};base64,{base64.b64encode(img_bytes).decode()}"

try:
    from deep_translator import GoogleTranslator
    def tr_ko(text: str) -> str:
        if not text: return ""
        try: return GoogleTranslator(source="auto", target="ko").translate(text)
        except Exception: return text
    _HAS_TR = True
except Exception:
    def tr_ko(text: str) -> str: return text or ""
    _HAS_TR = False

# ---------------------- Geolocation (IP 기반) ----------------------
@st.cache_data(ttl=3600*24) # 24시간 캐싱
def get_user_ip_geolocation():
    """IP 주소 기반으로 사용자 위치 (위도, 경도, 도시)를 추정합니다."""
    try:
        response = requests.get("http://ip-api.com/json/?fields=lat,lon,city,status,message", timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            return data.get("lat"), data.get("lon"), data.get("city")
        else:
            st.warning(f"IP 기반 위치 정보를 가져오지 못했습니다: {data.get('message', '알 수 없는 오류')}")
            return None, None, None
    except requests.exceptions.RequestException as e:
        st.error(f"IP 기반 위치 정보 요청 오류: {e}. 기본 위치를 사용합니다.")
        return None, None, None

# ---------------------- KMA API Session (HTTP 우선) ----------------------
def kma_get(url: str, params: dict, timeout: tuple = (5, 20)) -> Optional[requests.Response]:
    """
    KMA API를 HTTP로 직접 호출합니다. (보안 취약점 주의!)
    """
    headers = {"User-Agent": "SmartAgri/1.0 (HTTP-First)"}
    # HTTPS 대신 HTTP로 URL 강제 변환
    if url.startswith("https://"):
        http_url = "http://" + url[8:]
    else:
        http_url = url
    
    try:
        r = requests.get(http_url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.RequestException as e:
        st.error(f"KMA API 호출 중 오류 발생: {e}") # 오류 발생 시만 출력
        return None


# ---------------------- Tools (Optional) ----------------------
# 1) Weather (KMA) - 초단기 실황 + POP
def latlon_to_grid(lat, lon):
    """위도/경도를 기상청 격자 좌표로 변환합니다."""
    RE=6371.00877; GRID=5.0; SLAT1,SLAT2=30.0,60.0; OLON,OLAT=126.0,38.0; XO,YO=43,136
    DEGRAD=math.pi/180.0; re=RE/GRID
    slat1,slat2=SLAT1*DEGRAD,SLAT2*DEGRAD; olon,olat=OLON*DEGRAD,OLAT*DEGRAD
    sn=math.tan(math.pi*0.25+slat2*0.5)/math.tan(math.pi*0.25+slat1*0.5)
    sn=math.log(math.cos(slat1)/math.cos(slat2))/math.log(sn)
    sf=math.tan(math.pi*0.25+slat1*0.5); sf=(sf**sn)*(math.cos(slat1)/sn)
    ro=math.tan(math.pi*0.25+olat*0.5); ro=re*sf/(ro**sn)
    ra=math.tan(math.pi*0.25+lat*DEGRAD*0.5); ra=re*sf/(ra**sn)
    theta=lon*DEGRAD-olon
    if theta>math.pi: theta-=2.0*math.pi
    if theta<-math.pi: theta+=2.0*math.pi
    theta*=sn
    x=ra*math.sin(theta)+XO; y=ro-ra*math.cos(theta)+YO
    return int(x+1.5), int(y+1.5)

def kma_ultra_now(lat: float, lon: float) -> Optional[dict]:
    """기상청 초단기 실황 정보를 가져옵니다 (T1H, REH, RN1)."""
    if not KMA_API_KEY:
        st.error("KMA_API_KEY가 설정되지 않았습니다. .streamlit/secrets.toml을 확인하세요.")
        return None
    nx, ny = latlon_to_grid(lat, lon)
    kst = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
    base_dt = kst - dt.timedelta(minutes=45)
    base_date = base_dt.strftime("%Y%m%d")
    base_time = base_dt.strftime("%H") + "00"
    
    url = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
    params = {"serviceKey":KMA_API_KEY,"dataType":"JSON","numOfRows":200,"pageNo":1,
                "base_date":base_date,"base_time":base_time,"nx":nx,"ny":ny}
    r = kma_get(url, params)
    if not r: return None
    try:
        json_response = r.json()
        if json_response.get("response", {}).get("header", {}).get("resultCode") != "00":
             st.error(f"KMA 초단기 실황 API 응답 오류: {json_response.get('response', {}).get('header', {}).get('resultMsg')}")
             return None
        items = json_response["response"]["body"]["items"]["item"]
        d = {i["category"]: i["obsrValue"] for i in items}
        return {"T1H": d.get("T1H"), "REH": d.get("REH"), "RN1": d.get("RN1"),
                "meta":{"nx":nx,"ny":ny,"base_date":base_date,"base_time":base_time}}
    except KeyError as ke:
        st.error(f"KMA 응답 JSON 구조 오류 (KeyError): {ke}. 응답 내용: {r.text}")
        return None
    except Exception as e:
        st.error(f"초단기 실황 데이터 파싱 중 오류 발생: {e}")
        return None

def _latest_vilage_base_time(kst: dt.datetime)->str:
    """단기 예보의 최신 base_time을 계산합니다."""
    slots=[2,5,8,11,14,17,20,23]
    hh=kst.hour
    base=max([h for h in slots if h<=hh] or [23]); return f"{base:02d}00"

def kma_vilage_pop(lat: float, lon: float) -> Optional[dict]:
    """기상청 단기 예보의 강수 확률(POP)을 가져옵니다."""
    if not KMA_API_KEY:
        st.error("KMA_API_KEY가 설정되지 않았습니다. .streamlit/secrets.toml을 확인하세요.")
        return None
    nx, ny = latlon_to_grid(lat, lon)
    kst = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
    base_date = kst.strftime("%Y%m%d"); base_time = _latest_vilage_base_time(kst)
    
    url = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    params = {"serviceKey":KMA_API_KEY,"dataType":"JSON","numOfRows":900,"pageNo":1,
                "base_date":base_date,"base_time":base_time,"nx":nx,"ny":ny}
    r = kma_get(url, params)
    if not r: return None
    try:
        json_response = r.json()
        response_body = json_response.get("response", {}).get("body", {})
        
        # KMA POP 오류 수정: totalCount가 0일 경우 NO_DATA_ERROR로 처리
        total_count = response_body.get("totalCount")
        if total_count == 0:
            st.warning(f"KMA API NO_DATA_ERROR (단기 예보): 해당 시간의 예보 데이터가 없습니다.")
            return None
        
        if response_body.get("resultCode") == "03": # 명시적인 NO_DATA_ERROR 코드
            st.warning(f"KMA API NO_DATA_ERROR (단기 예보): {response_body.get('resultMsg')}.")
            return None
        
        if json_response.get("response", {}).get("header", {}).get("resultCode") != "00":
             st.error(f"KMA 단기 예보 API 응답 오류: {json_response.get('response', {}).get('header', {}).get('resultMsg')}")
             return None

        items = response_body.get("items", {}).get("item", [])
        if not items: # items 리스트 자체가 비어있는 경우
            st.warning("KMA 단기 예보 데이터 항목이 비어 있습니다.")
            return None

        now_hhmm = kst.strftime("%H%M")
        pops = [it for it in items if it["category"]=="POP"]
        pops.sort(key=lambda x:(x["fcstDate"],x["fcstTime"]))
        
        for it in pops:
            if (it["fcstDate"] > base_date) or (it["fcstDate"] == base_date and it["fcstTime"] >= now_hhmm):
                return {"POP": it["fcstValue"], "fcstDate": it["fcstDate"], "fcstTime": it["fcstTime"]}
        
        if pops: # 현재 시간 이후 데이터가 없으면 마지막 POP 값 반환 (fallback)
            it=pops[-1]
            return {"POP": it["fcstValue"], "fcstDate": it["fcstDate"], "fcstTime": it["fcstTime"]}
        
        return None # POP 데이터 항목을 찾을 수 없는 경우
    except KeyError as ke:
        st.error(f"KMA 응답 JSON 구조 오류 (KeyError): {ke}. 응답 내용: {r.text}")
        return None
    except Exception as e:
        st.error(f"단기 예보 POP 데이터 파싱 중 오류 발생: {e}")
        return None

# 2) Plant.ID (이미지 진단)
def plantid_identify(image_bytes: bytes) -> Optional[dict]:
    """Plant.ID API를 사용하여 식물 또는 질병을 식별합니다."""
    if not PLANTID_API_KEY: return None
    url = "https://api.plant.id/v2/identify"
    headers = {"Api-Key": PLANTID_API_KEY, "Content-Type": "application/json"}
    payload = {
        "images": [base64.b64encode(image_bytes).decode()],
        "plant_details": ["common_names", "description", "url", "watering"],
        "disease_details": ["common_names", "description", "url", "treatment"],
        "modifiers": ["similar_images"]
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=(8, 30))
        r.raise_for_status(); return r.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Plant.ID API 호출 오류: {e}")
        return None

# --- NongsaRo Category Data & Fetching Functions ---
# 품목 카테고리 정보 캐싱 (메인/미들 카테고리 목록을 가져오는 함수)
@st.cache_data(ttl=3600*24*7) # 1주간 캐싱
def get_nongsaro_main_categories() -> List[Tuple[str, str]]:
    """농사로 API에서 메인 카테고리 목록을 가져옵니다."""
    if not NONGSARO_API_KEY: return []
    url = "http://api.nongsaro.go.kr/service/varietyInfo/mainCategoryList"
    params = {"apiKey": NONGSARO_API_KEY}
    
    try:
        r = requests.get(url, params=params, timeout=(5, 15))
        r.raise_for_status()
        xml_text = r.text
        root = ET.fromstring(xml_text)
        
        main_categories = [("선택하세요", "")] # 초기 선택 옵션
        items_tag = root.find('.//items')
        if items_tag is not None:
            for item in items_tag.findall('item'):
                category_name = item.find('categoryNm').text if item.find('categoryNm') is not None else ''
                category_code = item.find('categoryCode').text if item.find('categoryCode') is not None else ''
                if category_name and category_code:
                    main_categories.append((category_name, category_code))
        return main_categories
    except Exception as e:
        st.error(f"농사로 메인 카테고리 로드 오류: {e}")
        return []

@st.cache_data(ttl=3600*24*7) # 1주간 캐싱
def get_nongsaro_middle_categories(main_category_code: str) -> List[Tuple[str, str]]:
    """농사로 API에서 특정 메인 카테고리에 속하는 미들 카테고리 목록을 가져옵니다."""
    if not NONGSARO_API_KEY or not main_category_code: return []
    url = "http://api.nongsaro.go.kr/service/varietyInfo/middleCategoryList"
    params = {"apiKey": NONGSARO_API_KEY, "categoryCode": main_category_code} # categoryCode는 mainCategoryCode임
    
    try:
        r = requests.get(url, params=params, timeout=(5, 15))
        r.raise_for_status()
        xml_text = r.text
        root = ET.fromstring(xml_text)
        
        middle_categories = [("선택하세요", "")] # 초기 선택 옵션
        items_tag = root.find('.//items')
        if items_tag is not None:
            for item in items_tag.findall('item'):
                code_name = item.find('codeNm').text if item.find('codeNm') is not None else ''
                code_value = item.find('code').text if item.find('code') is not None else '' # 미들 카테고리는 'code' 태그 사용
                
                # --- 여기에 강화된 숫자 및 불필요한 문자 제거 로직 ---
                # 모든 숫자 제거 (YYYY년산, YYYY년, 단독 숫자 모두 포함)
                code_name = re.sub(r'\d+', '', code_name) 
                
                # 괄호 안의 내용 제거 (예: "(1234)", "(재배)", "(청주)" 등)
                code_name = re.sub(r'\s*\(.*\)\s*', '', code_name)
                
                # 기타 불필요한 기호나 반복되는 공백 제거
                code_name = re.sub(r'[^\w\s]', '', code_name) # 알파벳, 한글, 숫자(이미 위에서 제거됨), 공백 외 모두 제거
                code_name = re.sub(r'\s+', ' ', code_name) # 여러 공백을 하나로 축소
                
                code_name = code_name.strip() # 최종적으로 앞뒤 공백 제거
                
                if code_name and code_value:
                    middle_categories.append((code_name, code_value))
        return middle_categories
    except Exception as e:
        st.error(f"농사로 미들 카테고리 로드 오류 (메인:{main_category_code}): {e}")
        return []

# 3) 농사로 (품종정보 - varietyList 사용)
def nongsaro_info(crop_name: str, category_code: str) -> Optional[str]:
    """
    농사로 품종정보(varietyList)를 검색합니다.
    사용자가 선택한 category_code와 crop_name을 사용합니다.
    """
    if not NONGSARO_API_KEY:
        st.error("NONGSARO_API_KEY가 설정되지 않았습니다. .streamlit/secrets.toml을 확인하세요.")
        return None
    if not crop_name or not category_code:
        st.warning("농사로 검색을 위한 작물명 또는 카테고리가 제공되지 않았습니다.")
        return None

    name = crop_name.strip()
    original_search_name = name # 원본 검색어 보관
    if not any("가" <= ch <= "힣" for ch in name):
        try:
            name = GoogleTranslator(source="auto", target="ko").translate(name) if _HAS_TR else name
        except Exception:
            pass

    # --- 검색 시도 로직 (사용자 선택 카테고리 + 유사 작물명) ---
    found_text = None
    
    # 검색할 작물명 조합 (원본 작물명 + 유사 이름 휴리스틱)
    search_names_attempts = [name] 
    if original_search_name.lower() == 'corn' and '옥수수' not in search_names_attempts:
        search_names_attempts.append('옥수수') # 영어 'corn'의 명시적 한글명 추가
    
    # 유사 작물명 시도 (간단한 휴리스틱) - 농사로 데이터베이스에 정확히 일치하지 않을 때 대비
    if '옥수수' in name:
        if '찰옥수수' not in search_names_attempts: search_names_attempts.append('찰옥수수')
        if '단옥수수' not in search_names_attempts: search_names_attempts.append('단옥수수')
    if '고추' in name:
        if '청양고추' not in search_names_attempts: search_names_attempts.append('청양고추')
        if '꽈리고추' not in search_names_attempts: search_names_attempts.append('꽈리고추')
    if '감자' in name:
        if '수미감자' not in search_names_attempts: search_names_attempts.append('수미감자')
        if '대지감자' not in search_names_attempts: search_names_attempts.append('대지감자')
    if '상추' in name:
        if '꽃상추' not in search_names_attempts: search_names_attempts.append('꽃상추')
        if '청상추' not in search_names_attempts: search_names_attempts.append('청상추')
    
    search_names_attempts = list(dict.fromkeys(search_names_attempts)) # 중복 제거 (순서 유지)


    # 농사로 API URL (품종정보 varietyList)
    url = "http://api.nongsaro.go.kr/service/varietyInfo/varietyList" 
    
    for attempt_name in search_names_attempts:
        params = {
            "apiKey": NONGSARO_API_KEY,
            "categoryCode": category_code, # 사용자가 선택한 카테고리 코드 사용
            "svcCodeNm": attempt_name, # 시도할 작물명
            "numOfRows": 10, # 검색 결과 수
            "pageNo": 1 # 페이지 번호
        }
        
        try:
            r = requests.get(url, params=params, timeout=(5, 15))
            r.raise_for_status() 
            
            xml_text = r.text
            root = ET.fromstring(xml_text)
            header_tag = root.find('header')
            result_code = header_tag.find('resultCode').text if header_tag is not None else None
            result_msg = header_tag.find('resultMsg').text if header_tag is not None else None

            if result_code == "00": # 결과 코드가 정상이면 데이터 유무 확인
                items_tag = root.find('.//items')
                total_count_tag = items_tag.find('totalCount') if items_tag is not None else None
                total_count = int(total_count_tag.text) if total_count_tag is not None and total_count_tag.text.isdigit() else 0

                if total_count > 0: # 데이터 발견 시
                    texts = []
                    for item in items_tag.findall('item'):
                        svc_code_nm = item.find('svcCodeNm').text if item.find('svcCodeNm') is not None else 'N/A'
                        main_chartr_info = item.find('mainChartrInfo').text if item.find('mainChartrInfo') is not None else '정보 없음'
                        texts.append(f"[{svc_code_nm}] 주요특성: {main_chartr_info}")
                    
                    found_text = "\n\n".join(texts).strip()
                    return found_text 
                # else: totalCount가 0인 경우, 다음 시도로 넘어감
            else: # API 오류 응답
                error_details = f"농사로 API 응답 오류 (XML): 코드={result_code}, 메시지={result_msg} (시도: '{attempt_name}', 카테고리: '{category_code}', URL: {url})"
                if result_code == "11": error_details += " - 인증키 문제."
                elif result_code == "13": error_details += " - 유효한 요청 주소/파라미터가 아님."
                elif result_code == "15": error_details += " - 도메인 미등록 오류."
                elif result_code == "91": error_details += " - 농사로 시스템 오류."
                st.error(error_details)
                continue # 다음 시도로 넘어감
        except ET.ParseError as pe: # XML 파싱 오류 처리
            st.error(f"농사로 응답 XML 파싱 실패: {pe}. 응답 텍스트 (부분): {xml_text[:500]}...")
            continue # 다음 시도로 넘어감
        except requests.exceptions.RequestException as re:
            st.error(f"농사로 API 요청 오류: {re}. URL 또는 네트워크 연결을 확인하세요.")
            continue # 다음 시도로 넘어감
        except Exception as e:
            st.error(f"농사로 정보 가져오는 중 예상치 못한 오류 발생: {e}")
            continue # 다음 시도로 넘어감
        
    return None # 모든 시도 실패 시 None 반환

# 4) 스마트팜 코리아 (최근값)
def smartfarm_latest(base_url: str, device_id: str) -> Optional[dict]:
    """스마트팜 코리아 API를 사용하여 최신 센서 데이터를 가져옵니다."""
    if not (SMARTFARM_KOREA_API_KEY and base_url and device_id): return None
    headers = {"Authorization": f"Bearer {SMARTFARM_KOREA_API_KEY}"}
    url = f"{base_url.rstrip('/')}/devices/{device_id}/latest"
    try:
        r = requests.get(url, headers=headers, timeout=(5, 15))
        r.raise_for_status(); return r.json()
    except requests.exceptions.RequestException as e:
        st.error(f"스마트팜 API 호출 오류: {e}")
        return None

# 5) 농진청 국립농업과학원 농업기상 기본 관측데이터 조회
def rda_general_weather(lat: float, lon: float) -> Optional[dict]:
    """농진청 농업기상 기본 관측데이터를 가져옵니다. (예시 함수, 실제 API 파라미터 확인 필요)"""
    if not RDA_WEATHER_API_KEY: return None
    url = "https://apis.data.go.kr/1390802/AgriWeather/WeatherObsrInfo/V3/GnrlWeather"
    params = {
        "serviceKey": RDA_WEATHER_API_KEY,
        "dataType": "JSON",
        "numOfRows": "10",
        "pageNo": "1",
    }
    try:
        r = requests.get(url, params=params, timeout=(5, 15))
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        st.error(f"농진청 날씨 API 호출 오류 (기본 관측): {e}")
        return None

# 6) 농업기상 상세 관측데이터 조회
def rda_detailed_weather(station_id: str) -> Optional[dict]:
    """농진청 농업기상 상세 관측데이터를 가져옵니다. (예시 함수, 실제 API 파라미터 확인 필요)"""
    if not RDAD_WEATHER_API_KEY: return None
    url = f"https://apis.data.go.kr/1390802/AgriWeather/WeatherObsrInfo/V4/InsttWeather/{station_id}"
    params = {
        "serviceKey": RDAD_WEATHER_API_KEY,
        "dataType": "JSON",
    }
    try:
        r = requests.get(url, params=params, timeout=(5, 15))
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        st.error(f"농진청 날씨 API 호출 오류 (상세 관측): {e}")
        return None

# ---------------------- OpenAI Chat ----------------------
def ask_openai(messages: List[dict]) -> Optional[str]:
    """OpenAI GPT 모델에 질문하고 답변을 받습니다."""
    if not OPENAI_API_KEY:
        st.error("OPENAI_API_KEY가 없습니다. .streamlit/secrets.toml을 확인하세요.")
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-5-mini",
            messages=messages,
            #temperature=0.2, # 답변의 일관성과 정확성을 위해 낮은 온도 사용 (자유로운 답변은 프롬프트로 유도)
        )
        return resp.choices[0].message.content
    except Exception as e:
        st.error(f"OpenAI 호출 오류: {e}. API 키 또는 네트워크를 확인하세요.")
        return None

# ---------------------- State ----------------------
if "chat" not in st.session_state: st.session_state.chat = []

# ---------------------- Sidebar (툴 허용/옵션) ----------------------
with st.sidebar:
    st.subheader("🔧 툴 사용 허용")
    use_weather   = st.toggle("기상청 날씨 (KMA)", value=True, help="T1H/REH/RN1/POP")
    use_plantid   = st.toggle("Plant.ID 이미지 진단", value=True, help="업로드된 이미지로 식물/질병 진단")
    use_nongsaro  = st.toggle("농사로 재배정보", value=True, help="작물명 검색 시 정보 제공") # 농사로 기본값 True
    use_smartfarm = st.toggle("스마트팜 코리아", value=False)
    
    st.caption("불안정하면 끄고 텍스트+이미지 질문만으로도 작동합니다.")

    # 날씨 툴 옵션
    st.markdown("---")
    st.markdown("**📍 위치 설정**")
    use_auto_location = st.checkbox("자동으로 현재 위치 가져오기 (IP 기반)", value=True, help="IP 주소 기반이므로 정확도가 낮을 수 있습니다.")
    
    lat = None
    lon = None
    city_name = "알 수 없음"

    if use_auto_location:
        auto_lat, auto_lon, auto_city = get_user_ip_geolocation()
        if auto_lat and auto_lon:
            lat = auto_lat
            lon = auto_lon
            city_name = auto_city or "자동 감지 위치"
            st.info(f"자동 감지 위치: {city_name} (위도: {lat:.4f}, 경도: {lon:.4f})")
        else:
            st.warning("자동 위치 감지 실패. 기본 위치를 사용하거나 수동으로 입력해주세요.")
            lat = 36.628956 # 청주 기본값
            lon = 127.462127 # 청주 기본값
            city_name = "청주 (기본값)"
    else:
        st.markdown("**수동 위치 입력**")
        lat = st.number_input("위도", value=36.628956, format="%.6f", help="날씨 정보를 가져올 위치의 위도")
        lon = st.number_input("경도", value=127.462127, format="%.6f", help="날씨 정보를 가져올 위치의 경도")
        city_name = "수동 입력 위치"
    
    st.text(f"현재 선택된 날씨 조회 위치: {city_name}")


    # 농사로 툴 옵션 (질문 입력 전 선택)
    selected_nongsaro_crop_info = None
    if use_nongsaro:
        st.markdown("---")
        st.markdown("**🌱 농사로 작물 선택**")

        # 1단계: 메인 카테고리 선택
        main_categories = get_nongsaro_main_categories()
        main_category_options = [name for name, code in main_categories]
        selected_main_category_name = st.selectbox(
            "메인 카테고리", 
            options=main_category_options, 
            index=0 if "선택하세요" in main_category_options else 0,
            key="main_cat_select", # 고유 키 추가
            help="작물의 대분류를 선택하세요."
        )
        selected_main_category_code = next((code for name, code in main_categories if name == selected_main_category_name), "")

        # 2단계: 미들 카테고리 선택 (메인 카테고리가 선택된 경우에만)
        selected_middle_category_name = ""
        selected_middle_category_code = ""
        if selected_main_category_code and selected_main_category_code != "": # '선택하세요'가 아닌 유효한 코드일 때만
            middle_categories = get_nongsaro_middle_categories(selected_main_category_code)
            middle_category_options = [name for name, code in middle_categories]
            selected_middle_category_name = st.selectbox(
                "세부 카테고리",
                options=middle_category_options,
                index=0 if "선택하세요" in middle_category_options else 0,
                key="middle_cat_select", # 고유 키 추가
                help="메인 카테고리 내에서 세부 작물 분류를 선택하세요."
            )
            selected_middle_category_code = next((code for name, code in middle_categories if name == selected_middle_category_name), "")
        
        # 3단계: 품목(작물)명 직접 입력 (선택된 미들 카테고리 기반)
        # 세부 카테고리 선택 시 자동으로 해당 카테고리 이름으로 검색되도록 함
        default_crop_name_input = selected_middle_category_name if selected_middle_category_name and selected_middle_category_name != "선택하세요" else ""
        
        # 사용자가 입력한 품목명이 있으면 그 값 사용, 없으면 default_crop_name_input 사용 (세부 카테고리 이름)
        crop_hint_input_from_user = st.text_input(
            "농사로 검색 품목명 (선택 또는 자동)", # '선택' 제거, '생략 가능' 추가
            value=default_crop_name_input, # 초기값으로 세부 카테고리 이름을 설정
            key="crop_name_input", # 고유 키 추가
            help="선택된 세부 카테고리명으로 자동 검색됩니다. 특정 품목을 원하면 직접 입력하세요. 예: 옥수수"
        )
        
        # 최종적으로 농사로 검색에 사용할 품목명 결정
        # 사용자가 직접 입력했으면 그 값, 아니면 세부 카테고리 이름
        final_crop_name_for_search = crop_hint_input_from_user if crop_hint_input_from_user else default_crop_name_input

        # 최종 선택된 품목 정보를 묶어서 저장
        # 미들 카테고리가 선택되면 품목명이 비어있어도 해당 미들 카테고리 이름으로 검색 (자동 검색)
        if selected_middle_category_code and selected_middle_category_code != "선택하세요" and final_crop_name_for_search:
            selected_nongsaro_crop_info = {
                "category_code": selected_middle_category_code,
                "crop_name": final_crop_name_for_search
            }
            st.info(f"농사로 검색을 위해 '{selected_middle_category_name}' 카테고리의 '{final_crop_name_for_search}' 품목이 선택되었습니다.")
        elif selected_main_category_code and selected_main_category_code != "선택하세요":
            st.warning("농사로 품종 정보를 검색하려면 세부 카테고리를 선택해야 합니다.")
        elif crop_hint_input_from_user:
            st.warning("농사로 품종 정보를 검색하려면 메인/세부 카테고리를 먼저 선택해주세요. (입력된 품목: " + crop_hint_input_from_user + ")")
        else:
            st.info("농사로 검색을 위해 품목을 선택하거나 입력해주세요.")


    # 스마트팜 툴 옵션
    sf_base = sf_dev = None
    if use_smartfarm:
        st.markdown("**스마트팜 연결 정보**")
        sf_base = st.text_input("스마트팜 Base URL", help="예: https://api.your_smartfarm.com")
        sf_dev  = st.text_input("Device ID", help="연결할 특정 장치의 ID")


# ---------------------- Main: Chat-first UI ----------------------
st.markdown("## 🤖 코파일럿 대화")
colA, colB = st.columns([0.72, 0.28], vertical_alignment="top")

with colA:
    # 대화 로그 렌더링
    for turn in st.session_state.chat:
        with st.chat_message("user"):
            if turn.get("image"): st.image(turn["image"], use_container_width=True)
            st.write(turn["q"])
        with st.chat_message("assistant"):
            st.write(turn["a"])

    # 사용자 입력 영역
    q = st.chat_input("질문을 입력하세요. 예) 병징 사진과 함께 물주기/방제/환기 전략 추천")

with colB:
    qimg_file = st.file_uploader("이미지(선택)", type=["jpg","jpeg","png"], help="진단 및 분석에 활용할 이미지를 업로드하세요.")

# ---------------------- On send ----------------------
if q is not None:
    # 1) 컨텍스트 수집 (옵션 툴 호출)
    ctx = {"weather": None, "plantid": None, "nongsaro": None, "smartfarm": None}
    status_notes = []

    # 날씨 (KMA)
    if use_weather and lat is not None and lon is not None:
        now_weather = kma_ultra_now(lat, lon)
        pop_weather = kma_vilage_pop(lat, lon)
        
        if now_weather or pop_weather:
            ctx["weather"] = {
                "T1H": (now_weather or {}).get("T1H"), "REH": (now_weather or {}).get("REH"),
                "RN1": (now_weather or {}).get("RN1"), "POP": (pop_weather or {}).get("POP"),
                "meta": (now_weather or {}).get("meta")
            }
            status_notes.append("날씨(KMA) OK ✅")
        else:
            status_notes.append("날씨(KMA) 불가 ❌")
    elif use_weather:
        status_notes.append("날씨(KMA) 불가 (좌표 미입력) ❌")
    else:
        status_notes.append("날씨(KMA) 비활성화")


    # Plant.ID (이미지 업로드 시)
    img_data_url = None
    if use_plantid and qimg_file is not None:
        res = plantid_identify(qimg_file.getvalue())
        if res:
            try:
                s0 = res.get("suggestions", [{}])[0]
                plant_name = (s0.get("plant_details", {}).get("common_names") or [s0.get("plant_name")])[0]
                disease = s0.get("disease_suggestions", [{}])[0].get("common_name") if s0.get("disease_suggestions") else None
                ctx["plantid"] = {"name": plant_name, "disease": disease}
                status_notes.append("Plant.ID OK")
            except Exception as e:
                ctx["plantid"] = True
                status_notes.append(f"Plant.ID 일부 오류: {e}")
        else:
            status_notes.append("Plant.ID 불가")
    elif use_plantid:
        status_notes.append("Plant.ID 비활성화 (이미지 없음)")
    else:
        status_notes.append("Plant.ID 비활성화")


    # 농사로 (작물명 및 카테고리 선택 값 활용)
    if use_nongsaro:
        # selected_nongsaro_crop_info는 사이드바에서 선택된 최종 값 (category_code, crop_name 포함)
        if selected_nongsaro_crop_info and selected_nongsaro_crop_info["crop_name"] and selected_nongsaro_crop_info["category_code"]:
            # 선택된 작물명과 카테고리 코드로 농사로 API 호출
            txt = nongsaro_info(selected_nongsaro_crop_info["crop_name"], selected_nongsaro_crop_info["category_code"])
            if txt:
                ctx["nongsaro"] = {"crop": selected_nongsaro_crop_info["crop_name"], "text": txt[:1500]}
                status_notes.append("농사로 OK")
            else:
                status_notes.append("농사로 불가 (정보 없음)")
        else:
            status_notes.append("농사로 불가 (작물/카테고리 미선택)")
            
    # 스마트팜 (URL 및 Device ID 입력 시)
    if use_smartfarm and sf_base and sf_dev:
        sf = smartfarm_latest(sf_base, sf_dev)
        if sf:
            ctx["smartfarm"] = sf
            status_notes.append("스마트팜 OK")
        else:
            status_notes.append("스마트팜 불가")
    else:
        status_notes.append("스마트팜 비활성화")

    # 2) 메시지 구성 (멀티모달)
    # OpenAI 역할 부여 강화
    sys_prompt = (
        "당신은 최고 수준의 한국 농업 전문가이자 농부의 코파일럿입니다.\n"
        "사용자의 질문과 제공된 컨텍스트(날씨, 작물 진단, 농사로 정보, 스마트팜 센서 데이터)를 종합하여,\n"
        "다음 원칙에 따라 실용적이고 명확하며 실행 가능한 조언을 제공하세요:\n"
        "1. **문제 해결 및 예방**: 현재 문제(병해충, 이상 기후 등)를 해결하고, 발생 가능한 위험을 예방하는 데 초점을 맞춥니다.\n"
        "2. **단계별 지침**: 농부가 즉시 따라 할 수 있는 구체적인 단계와 절차를 제시합니다.\n"
        "3. **안전 우선**: 기상, 시설, 병해충 정보가 불완전하거나 불확실할 경우, 항상 안전을 최우선으로 하는 조언을 합니다.\n"
        "4. **법규 준수**: 농약/약제 사용 시에는 반드시 제품 라벨 및 지역 농업 관련 법규/규정을 준수하도록 안내합니다.\n"
    )

    if ctx["weather"]:
        weather_info = []
        if ctx["weather"].get("T1H"): weather_info.append(f"기온: {ctx['weather']['T1H']}°C")
        if ctx["weather"].get("REH"): weather_info.append(f"습도: {ctx['weather']['REH']}%")
        if ctx["weather"].get("RN1"): weather_info.append(f"강수량: {ctx['weather']['RN1']}mm")
        if ctx["weather"].get("POP"): weather_info.append(f"강수 확률: {ctx['weather']['POP']}%")
        
        if weather_info:
            sys_prompt += f"\n- KMA 날씨 정보: {', '.join(weather_info)}."
            if ctx["weather"].get("meta"):
                sys_prompt += f" (기준: {ctx['weather']['meta']['base_date']} {ctx['weather']['meta']['base_time']})"
        else:
             sys_prompt += f"\n- KMA 날씨 정보는 가져왔으나, 유효한 상세 데이터가 없습니다."
    else:
        sys_prompt += f"\n- 날씨 정보를 가져오지 못했습니다. 이 정보 없이 답변을 생성해야 합니다."
    
    if ctx["plantid"] and ctx["plantid"].get("name"):
        sys_prompt += f"\n- 이미지 진단 결과, 작물: '{ctx['plantid']['name']}'."
    if ctx["plantid"] and ctx["plantid"].get("disease"):
        sys_prompt += f" 의심되는 질병: '{ctx['plantid']['disease']}'. 이에 대한 방제 조언을 최우선으로 고려하세요."
    if ctx["nongsaro"] and ctx["nongsaro"].get("text"):
        sys_prompt += f"\n- 농사로에서 가져온 '{ctx['nongsaro']['crop']}' 관련 정보: {ctx['nongsaro']['text']}"
    if ctx["smartfarm"] :
         sys_prompt += f"\n- 스마트팜 센서 데이터: {json.dumps(ctx['smartfarm'], ensure_ascii=False)}"

    sys = {"role": "system", "content": sys_prompt}

    user_content = []
    user_content.append({"type": "text", "text": q})
    if qimg_file is not None:
        mime = "image/png" if qimg_file.name.lower().endswith("png") else "image/jpeg"
        img_data_url = img_to_data_url(qimg_file.getvalue(), mime)
        user_content.append({"type": "image_url", "image_url": {"url": img_data_url}})

    # 3) OpenAI 호출
    with st.spinner("답변 생성 중..."):
        out = ask_openai([sys, {"role": "user", "content": user_content}])

    # 4) 렌더링 & 로그 저장
    with st.chat_message("user"):
        if qimg_file is not None:
            st.image(qimg_file, use_container_width=True)
        st.write(q)
    with st.chat_message("assistant"):
        if status_notes:
            st.caption(" / ".join(status_notes))
        st.write(out or "답변 생성 실패")

    st.session_state.chat.append({
        "q": q,
        "image": (Image.open(qimg_file) if qimg_file else None),
        "a": out or ""
    })