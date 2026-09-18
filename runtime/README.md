# 로컬 서비스 실행 데이터

서비스 실행 시 생성할 uploads/, artifacts/, db/ 디렉터리의 위치입니다. README만 버전 관리합니다. 실행 데이터와 DB는 Git에 커밋하지 않습니다.

API와 worker의 storage root는 환경 설정 CTFM_STORAGE_ROOT로 동일한 절대 경로를 지정합니다. 기본은 저장소 runtime입니다. 디렉터리 생성은 서비스 startup 책임이며 현재 실행 파일은 없습니다.
