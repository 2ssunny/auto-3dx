# auto-3dx

`auto-3dx`는 외부 Python 프로세스에서 Windows COM을 통해
3DEXPERIENCE CATIA Automation object model을 사용하는 Python 라이브러리다.

현재는 실행 중인 3DEXPERIENCE 세션 연결과 읽기 전용 inspection을 검증하는 초기 단계다.
CATIA API는 로컬 설치본의 Automation documentation과 type library에서 확인한 뒤 단계적으로
추가한다.

## Repository structure

```text
auto-3dx/
├─ src/
│  └─ auto_3dx/
│     ├─ transport/
│     ├─ core/
│     ├─ inspect/
│     ├─ parameters/
│     └─ formulas/
├─ scripts/
│  └─ probes/
├─ tests/
│  ├─ unit/
│  └─ integration/
├─ examples/
└─ docs/
```

### `src/auto_3dx`

배포할 Python 패키지의 소스 디렉터리다. 최종 사용자는 이 패키지를 통해 `Catia` 같은
고수준 API를 사용한다. 안정된 공개 이름만 최상위 `auto_3dx` 패키지에서 제공한다.

### `src/auto_3dx/transport`

Python과 3DEXPERIENCE 사이의 연결 계층이다. `pywin32`, 설치본의 `com3dx`, Windows
Running Object Table과 같은 COM 세부 사항을 이 영역에 격리한다.

상위 계층은 어떤 COM client를 사용하는지 몰라도 동작해야 한다. 연결 방법이 바뀌더라도
`core`, `parameters` 같은 고수준 API에 미치는 영향을 최소화하는 것이 목적이다.

### `src/auto_3dx/core`

3DEXPERIENCE의 Application, Editor, Part 같은 핵심 객체를 감싸는 고수준 wrapper를 둔다.
COM 객체의 생명주기, 공통 오류 변환, update 같은 공통 동작도 이 계층의 책임이다.

### `src/auto_3dx/inspect`

현재 CATIA 세션과 모델 상태를 변경하지 않고 읽는 기능을 둔다. Active Editor, 현재 편집
객체, feature tree, parameter 목록처럼 사람이거나 AI agent가 모델을 이해하는 데 필요한
정보를 일관된 형식으로 제공한다.

### `src/auto_3dx/parameters`

CATIA Parameter의 탐색, 값 읽기, 값 변경, 단위 처리와 생성 기능을 둔다. 반복 실행 시
안전한 `ensure` 동작도 실제 CATIA 환경에서 동작을 확인한 후 이 영역에 추가한다.

### `src/auto_3dx/formulas`

Formula와 Relation을 탐색하고 생성하거나 수정하는 기능을 둔다. Parameter 기능과 CATIA
update 절차가 검증된 뒤 구현한다.

### `scripts/probes`

라이브러리 API로 확정하기 전의 작은 진단 프로그램을 둔다. 설치본의 `com3dx` import,
실행 중인 세션 attach, Active Editor 접근 같은 가설을 한 번에 하나씩 검증한다.

probe는 현재 환경을 조사하기 위한 개발 도구다. 검증이 끝난 동작만 `src/auto_3dx`의
라이브러리 코드로 옮긴다.

### `tests/unit`

실행 중인 CATIA 없이 검증할 수 있는 단위 테스트를 둔다. 값 변환, 오류 처리, 고수준 API의
일반 로직처럼 COM 세션이 필요하지 않은 동작을 대상으로 한다.

### `tests/integration`

실제 실행 중인 3DEXPERIENCE와 설치된 Automation 환경이 필요한 통합 테스트를 둔다.
일반 단위 테스트 실행에 자동으로 포함하지 않고, 필요한 조건을 명시해 선택적으로 실행한다.

### `examples`

검증을 마친 공개 `auto_3dx` API의 사용 예제를 둔다. 조사 중인 raw COM 코드나 임시
실험 코드는 여기에 두지 않는다.

### `docs`

로컬 `DSYAutomation.chm`, 등록된 type library와 실제 CATIA 실행 결과에서 확인한 내용을
기록한다. 릴리스별 차이, 지원하는 객체와 메서드, 안전한 작업 순서도 이 영역에서 관리한다.

## Dependency direction

라이브러리 내부의 의존 방향은 다음과 같이 유지한다.

```text
auto_3dx public API
        ↓
inspect / parameters / formulas
        ↓
core
        ↓
transport
        ↓
com3dx / pywin32 / Windows COM
```

COM 객체와 연결 세부 사항은 `transport` 밖으로 직접 노출하지 않는다. 각 Automation 기능은
공식 문서에서 확인하고 실제 3DEXPERIENCE 환경에서 성공한 뒤 상위 API로 승격한다.
