# auto-3dx

`auto-3dx`는 외부 Python 프로세스에서 Windows COM을 통해 실행 중인
3DEXPERIENCE CATIA 세션에 연결하고, 열려 있는 Part를 자동화하는 Python
라이브러리입니다.

현재 공개 API는 다음 작업을 지원합니다.

- 실행 중인 3DEXPERIENCE 세션 attach
- 열린 Editor와 Part 선택
- 사용자 Parameter 생성·조회·변경
- Formula 생성·조회·변경
- Sketch와 2D 프로파일 생성 (원점 평면 또는 사용자 정의 offset/각도 평면 위)
- Sketch constraint 지정
- Pad, Pocket, Shaft, Groove, Mirror, Rib, Slot 생성
- 사각 패턴 생성 API
- 모서리 필렛 / 챔퍼, 면 참조 기반 Shell / Thickness / Hole 생성 API
- 솔리드의 부피·면적·질량·무게중심 측정 (기본 대상: main body)

Part 자체의 PLM 생성과 저장은 이 라이브러리의 책임 범위가 아닙니다. 먼저
3DEXPERIENCE에서 Part를 만들고 열어 둔 뒤 `auto-3dx`를 사용해야 합니다.

## 요구 사항

- Windows, 64-bit Python 3.11 이상 (검증된 버전은 아래 표)
- 실행 중인 3DEXPERIENCE CATIA 세션
- 3DEXPERIENCE 설치본의 `com3dx.py` (설치본에 들어 있으며 pip로 설치하지 않습니다)
- `pywin32` (패키지 설치 시 자동 설치)

Conda는 필요하지 않습니다. pip로 의존성을 설치할 수 있는 일반 Python 환경이면 됩니다.
`com3dx.py`는 Python 환경이 아니라 3DEXPERIENCE 설치본에서 찾습니다(아래
"com3dx 경로 지정").

현재 실제 검증 대상은 `B428_Cloud` 설치본입니다. 릴리스에 따라 Automation
object model이나 설치 경로가 달라질 수 있으므로, 다른 릴리스는 별도로
검증해야 합니다.

### 검증된 Python 환경

2026-09-15, B428_Cloud에서 확인한 조합입니다.

| 환경 | Python | pywin32 | 설치 방법 | 단위 테스트 | live 통합 테스트 |
|---|---|---|---|---|---|
| 표준 CPython venv | 3.14.2 (python.org, 64-bit) | 312 | `pip install -e .` | 868 통과 | 40 통과 |
| 표준 CPython venv | 3.14.2 (python.org, 64-bit) | 312 | `pip install ".[test]"` (editable 아님) | 868 통과 | 실행 안 함 |
| Conda env | 3.11.16 (Anaconda, 64-bit) | 312 | `pip install -e .` | 868 통과 | 38 통과, 1 skip (In-Work Object 검사 추가 전) |
| Conda base | 3.13.9 (Anaconda, 64-bit) | 311 | 설치 없이 `PYTHONPATH=src` | 868 통과 | 개발 중 실행, 통과 |

두 live 실행 모두 실행 전후 모델, selection, In-Work Object가 같았습니다.

GitHub Actions Windows runner(3DEXPERIENCE 없음)에서도 표준 CPython 3.11, 3.12, 3.13,
3.14로 `pip install ".[test]"` 후 단위 테스트가 모두 통과했습니다. Python 3.12는 이 CI
단위 테스트로만 확인했고 live 통합 테스트는 실행하지 않았습니다. 위에 없는 조합(32-bit
Python, Microsoft Store Python, 다른 3DEXPERIENCE 릴리스)은 검증하지 않았습니다.

## 설치

표준 CPython으로 가상 환경을 만들고 저장소 루트에서 설치합니다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Conda를 쓴다면 환경을 활성화한 뒤 같은 `python -m pip install -e .`를 실행합니다.
어느 쪽이든 `pywin32`는 pip가 설치하고, 첫 연결 때 `com3dx`가 그 Python 전용
COM wrapper cache(`%TEMP%\gen_py\<버전>`)를 만듭니다. 새 환경의 첫 `Catia.attach()`는
그래서 몇 초 더 걸릴 수 있습니다.

`pyproject.toml`이 패키지 이름과 import 이름을 다음처럼 구분합니다.

```text
배포 이름: auto-3dx
import 이름: auto_3dx
```

설치 후에는 `PYTHONPATH`를 직접 설정하지 않고 사용할 수 있습니다.

## 빠른 시작

3DEXPERIENCE에서 작업할 Part를 열어 둔 뒤 다음을 실행합니다.

```python
from auto_3dx import Catia

catia = Catia.attach()
part = catia.active_part()

print(catia.name)
print(part.name)
print(part.parameters.user_names())
```

`Catia.attach()`는 새 CATIA 프로세스를 실행하지 않습니다. 실행 중인 세션에
연결하지 못하면 `CatiaConnectionError`, `Com3dxNotFoundError` 같은
`Auto3dxError` 계열 예외를 발생시킵니다.

### com3dx 경로 지정

경로는 디렉터리가 아니라 `com3dx.py` 파일 전체 경로입니다. 탐색 순서는
명시적 경로, `AUTO_3DX_COM3DX_PATH` 환경 변수, CATIA.Application 레지스트리
순서입니다. 보통은 아무것도 지정하지 않아도 됩니다. 3DEXPERIENCE가 등록한
`CATIA.Application` COM 서버의 실행 파일 위치에서 `com3dx.py`를 찾으며, 표준 CPython
venv와 Conda 모두 이 경로로 연결했습니다. 여러 릴리스가 설치되어 특정 릴리스를
골라야 할 때만 경로를 지정합니다(`<release>`는 설치된 릴리스 폴더 이름입니다).

```python
from pathlib import Path

catia = Catia.attach(
    Path(r"C:\Program Files\Dassault Systemes\<release>\win_b64\code\python3dx\lib\com3dx.py")
)
```

또는 PowerShell에서 다음처럼 지정할 수 있습니다.

```powershell
$env:AUTO_3DX_COM3DX_PATH = 'C:\Program Files\Dassault Systemes\<release>\win_b64\code\python3dx\lib\com3dx.py'
python .\your_script.py
```

같은 Python 프로세스에서 이미 다른 설치 릴리스의 `com3dx`가 로드된 경우에는
안전하게 교체하지 않고 오류를 발생시킵니다. 다른 릴리스를 사용하려면 새
Python 프로세스에서 시작해야 합니다.

## 예외 처리

모든 예외는 `Auto3dxError`를 상속하고, 그 아래 다섯 범주로 묶여 있습니다.
"호출자가 그 뒤에 무엇을 할 수 있는가"로 나눈 것이라, 반응이 같다면 범주를,
다르다면 구체 클래스를 잡습니다.

| 범주 | 뜻 | 호출자가 할 일 |
|---|---|---|
| `SessionError` | 세션에 닿지 못함 | 3DEXPERIENCE 실행/설치 경로/편집 대상 확인 |
| `ValidationError` | COM 호출 전에 거부됨. 모델은 그대로다 | 인자를 고쳐서 재시도 |
| `NotFoundError` | 그 이름의 객체가 없음 | 이름 확인 |
| `ConflictError` | 모델의 이름·상태가 요청을 막음 | 기존 객체와의 충돌 해소 |
| `AutomationError` | CATIA가 COM 호출을 거부하거나 실패함 | `hresult`로 원인 확인, 필요하면 정리 |

`ValidationError`는 COM에 닿기 전에 거부됐다는, 즉 모델이 안 바뀌었다는 보장을
줍니다. 반대로 `AutomationError`는 COM 호출이 실제로 시도됐다는 뜻이라 모델이
바뀌었을 수 있고, `hresult` 속성과 원래 `pywintypes.com_error`를 `__cause__`로
갖습니다. `PartUpdateError`(`Part.Update()` 실패)와 `StaleSnapshotError`(모델이
바뀐 뒤 옛 snapshot 사용, `ValidationError` 하위)는 흔히 개별로 잡을 만해서
루트에서도 바로 import할 수 있습니다.

```python
from auto_3dx import Catia, PartUpdateError, ValidationError

try:
    ...
except PartUpdateError:
    design.remove_pad(pad_name)
    raise
except ValidationError:
    ...  # 모델은 그대로다. 인자만 고치면 된다
```

나머지 구체 클래스는 각자의 패키지에서 가져옵니다. 예를 들어
`from auto_3dx.errors import SketchNotFoundError`. 전체 목록과 분류는
[`docs/capabilities.md`](docs/capabilities.md)에 있습니다.

## Part 선택

`ActiveEditor`가 UI에서 선택한 탭을 항상 따라간다고 가정하면 안 됩니다. 현재
활성 객체가 확실한 경우에는 `active_part()`를 사용하고, 여러 탭 중 하나를
선택해야 하는 경우에는 Editor 목록이나 이름 기반 선택을 사용합니다.

```python
active_part = catia.active_part()

for editor in catia.editors():
    print(editor.name, editor.object_kind, editor.object_name, editor.is_part)

open_parts = catia.parts()
named_part = catia.part_named("3D Shape00422534")
```

`catia.active_editor()`는 raw Editor COM 객체를 반환합니다. `part.com_object`도
raw Part에 접근하는 escape hatch이지만, 일반적인 애플리케이션 코드는 wrapper
API를 사용하는 편이 안전합니다. Assembly context의
`VPMRootOccurrence`는 Part로 자동 변환하지 않고 `NoActivePartError`를
발생시킵니다.

## Parameter

`part.parameters.list()`는 CATIA가 노출하는 전체 Parameter를 반환합니다. 여기에는
Pad, Sketch 등의 feature 내부 Parameter도 포함됩니다. 사람이 직접 만든
Parameter만 필요하면 `user_parameters()` 또는 `user_names()`를 사용합니다.

```python
parameters = part.parameters

for parameter in parameters.user_parameters():
    print(parameter.short_name, parameter.kind, parameter.value, parameter.unit)

width = parameters.ensure_length("WIDTH", 60, unit="mm")
parameters.ensure_real("SAFETY_FACTOR", 1.2)
parameters.ensure_integer("COUNT", 3)
parameters.ensure_string("LABEL", "demo")
parameters.ensure_boolean("ENABLED", True)

parameters.set("WIDTH", 80, unit="mm")
part.update()
```

지원되는 생성·재사용 API는 다음과 같습니다.

```python
parameters.create_length(name, value, unit="mm")
parameters.ensure_length(name, value, unit="mm")

parameters.create_real(name, value)
parameters.ensure_real(name, value)
parameters.create_integer(name, value)
parameters.ensure_integer(name, value)
parameters.create_string(name, value)
parameters.ensure_string(name, value)
parameters.create_boolean(name, value)
parameters.ensure_boolean(name, value)

parameters.create_dimension(name, magnitude, value)
parameters.ensure_dimension(name, magnitude, value)
```

`ensure_*`는 이름이 없으면 생성하고, 있으면 같은 종류인지 확인한 뒤 값을
갱신합니다. 다른 종류의 Parameter를 조용히 덮어쓰지 않습니다. `Parameter`는
`name`, `short_name`, `kind`, `value`, `magnitude`, `unit`, `info()`를 제공합니다.

단위 변환은 수행하지 않습니다. `unit` 인자는 지원 여부와 대상 Parameter의
단위를 확인하는 용도이며, 입력값을 다른 단위로 환산하지 않습니다.

```python
print(parameters.units.magnitudes())
print(parameters.units.units("Length"))
print(parameters.units.symbols("Length"))
print(parameters.units.supports("Length", "mm"))
```

## Formula

Formula 본문에 `Parameter.name`을 직접 넣으면 안 됩니다. CATIA가 Formula에서
사용할 이름은 `relation_name(parameter)`로 얻어야 합니다.

```python
driver = part.parameters.get("WIDTH")
pad = part.part_design.get_pad("BASE_PAD")

body = f"{part.formulas.relation_name(driver)} * 2"
formula = part.formulas.ensure(
    "PAD_HEIGHT_FROM_WIDTH",
    pad.depth_parameter(),
    body,
)

part.update()
print(formula.name, formula.body, formula.activated)
```

`FormulaCollection`은 `list()`, `names()`, `get()`, `create()`, `ensure()`,
`remove()`를 제공합니다. 개별 Formula는 `body`, `comment`, `activated`,
`input_count` 조회와 `modify()`, `rename()`, `activate()`, `deactivate()`를
제공합니다.

Formula·Parameter 변경 후 재계산은 자동으로 일어나지 않습니다. 필요한 시점에
명시적으로 `part.update()`를 호출해야 합니다.

## Sketch와 2D geometry

현재 검증된 기본 평면은 `XY`, `YZ`, `ZX`입니다. `SketchCollection.ensure()`는
이름뿐 아니라 평면의 axis data도 확인합니다.

```python
sketch = part.sketches.ensure("BASE_SKETCH", support="XY")

with sketch.edit() as editor:
    bottom = editor.line(0, 0, 60, 0)
    right = editor.line(60, 0, 60, 40)
    editor.line(60, 40, 0, 40)
    editor.line(0, 40, 0, 0)
    editor.horizontal(bottom)
    editor.perpendicular(bottom, right)

part.update()
```

`SketchEditor`에서 다음을 사용할 수 있습니다.

```python
editor.point(x, y)
editor.line(x1, y1, x2, y2)
editor.circle(center_x, center_y, radius)
editor.arc(center_x, center_y, radius, start_param, end_param)
editor.spline([(x1, y1), (x2, y2), (x3, y3)])
editor.rectangle(width, height, origin_x=0.0, origin_y=0.0)
editor.set_construction(element, True)
```

geometry 메서드는 `SketchElement`를 반환합니다. `kind`는 CATIA 타입 이름(`"Line2D"`
등)이고, 반지름이나 좌표 같은 raw 속성이 필요하면 `element.com_object`로 읽습니다.
속성마다 live 검증 상태가 달라서 `SketchElement` 자체에는 geometry 읽기를 두지
않았습니다. `SketchElement`는 자기가 그려진 스케치를 기억하므로, 다른 스케치에서
그린 요소를 제약이나 `set_center_line`에 넘기면 CATIA에 닿기 전에
`ValidationError`가 납니다. 이전처럼 raw 2D COM 객체를 넘겨도 동작하지만 그 경우에는
스케치 검사를 하지 않습니다.

Sketch 편집 제약은 반드시 같은 `with sketch.edit()` 블록 안에서, geometry
메서드가 반환한 `SketchElement`를 사용해 지정해야 합니다.

```python
with sketch.edit() as editor:
    first = editor.line(0, 0, 60, 0)
    second = editor.line(60, 0, 60, 40)
    editor.horizontal(first)
    editor.perpendicular(first, second)
    editor.length(first, 60, unit="mm")

part.update()
```

검증된 constraint 메서드는 `horizontal`, `vertical`, `perpendicular`,
`parallel`, `coincident`, `concentric`, `tangent`, `length`, `radius`,
`distance`입니다. 생성 후에는 `sketch.constraints`에서 목록, 이름, 상태와
치수값을 조회할 수 있습니다. Constraint 삭제 API는 아직 제공하지 않습니다.

Shaft와 Groove의 회전 프로파일은 편집 중 얻은 line을
`sketch.set_center_line(line)`으로 지정해야 합니다. 프로파일은 회전축을
가로지르거나 축에 닿지 않는 검증된 형태여야 합니다.

## 사용자 정의 평면 (Offset / Angle)

원점 평면 3개(`XY`/`YZ`/`ZX`) 문자열은 그대로 동작합니다. 그 외에 `part.planes`
(`PlaneCollection`)로 offset 평면과 각도 평면을 만들고, 그 평면을 `support`로
넘겨 스케치할 수 있습니다.

```python
plane = part.planes.create_offset("TOP_OFFSET", support="XY", offset=30)
sketch = part.sketches.create("TOP_SKETCH", support=plane)

with sketch.edit() as editor:
    editor.rectangle(20, 20)
part.update()

part.part_design.create_pad("OFFSET_PAD", sketch, 10, unit="mm")
part.update()
```

각도 평면은 회전축으로 addressable한 3D 선이 필요합니다. 스케치 안의 2D 선이나
원점 평면 자체를 축으로 주면 생성은 되지만 `Part.Update()`가 실패하므로,
`create_angle`은 내부적으로 점 2개와 선 1개를 따로 만들어 축으로 씁니다.

```python
angled = part.planes.create_angle(
    "TILTED",
    support="XY",
    angle=45,
    axis_start=(0, 0, 0),
    axis_end=(0, 0, 10),
)
sketch_on_angle = part.sketches.create("TILTED_SKETCH", support=angled)
```

이 컬렉션이 만드는 평면과 각도 평면의 축 점·축 선은 전부 하나의 기하 세트
(`HybridBody`, 이름 `auto_3dx_Planes`)에 들어갑니다. `remove(plane)`은 평면
하나만 지우고, 각도 평면의 축 점 2개와 축 선은 남습니다. 이것까지 함께
지우려면 `remove_geometrical_set()`으로 이 컬렉션이 만든 것 전부를 지워야
합니다.

`ensure_offset`/`ensure_angle`은 제공하지 않습니다. 기하 세트 안의 도형을
이름으로 다시 찾아 읽는 경로가 검증되지 않았기 때문입니다. 재사용이 필요하면
호출자가 반환된 `Plane` 객체를 직접 들고 있어야 합니다. `sketches.ensure()`의
`support`도 여전히 원점 평면 문자열 3개만 받으므로, offset/각도 평면 위
스케치의 재사용은 `sketches.create()`로 직접 관리해야 합니다.

## Part Design

Part Design wrapper는 `part.part_design`에서 얻습니다. 생성 메서드는 모델을
변경하지만 `Part.Update()`를 자동으로 호출하지 않습니다.

```python
design = part.part_design

pad = design.ensure_pad("BASE_PAD", sketch, 12, unit="mm")
print(pad.name, pad.height, pad.depth)

pocket = design.create_pocket("CUT", sketch, 5, unit="mm")
pocket.set_depth(6, unit="mm")

part.update()
```

feature 변경 뒤 CATIA의 rebuild 상태는 `part.is_up_to_date()`로 확인할 수
있습니다. 기본 대상은 Part이며, Pad·Sketch 같은 auto_3dx wrapper나 raw CATIA
객체를 넘길 수도 있습니다.

```python
pad.set_height(20, unit="mm")
assert not part.is_up_to_date()
assert not part.is_up_to_date(pad)
part.update()
assert part.is_up_to_date()
```

이 값은 저장되지 않은 모든 변경을 감지하지 않습니다. 독립 사용자 Parameter
값만 바꾼 경우 Part가 계속 `True`였으므로, feature rebuild 상태로만
해석해야 합니다.

현재 wrapper가 제공하는 feature는 다음과 같습니다.

| Feature | 주요 API | 입력 |
|---|---|---|
| Pad | `pads`, `get_pad`, `create_pad`, `ensure_pad`, `remove_pad` | Sketch + 높이 |
| Pocket | `pockets`, `get_pocket`, `create_pocket`, `ensure_pocket`, `remove_pocket` | Sketch + 깊이 |
| Shaft | `shafts`, `get_shaft`, `create_shaft`, `ensure_shaft`, `remove_shaft` | 중심선이 있는 Sketch |
| Groove | `grooves`, `get_groove`, `create_groove`, `ensure_groove`, `remove_groove` | 중심선이 있는 Sketch |
| Mirror | `mirrors`, `get_mirror`, `create_mirror`, `ensure_mirror`, `remove_mirror` | `XY`/`YZ`/`ZX` 평면 |
| Rib | `ribs`, `get_rib`, `create_rib`, `ensure_rib`, `remove_rib` | profile Sketch + path Sketch |
| Slot | `slots`, `get_slot`, `create_slot`, `ensure_slot`, `remove_slot` | profile Sketch + path Sketch |
| Edge Fillet | `edge_fillets`, `get_edge_fillet`, `create_edge_fillet`, `remove_edge_fillet` | `Edge` (`ensure_*` 없음) |
| Chamfer | `chamfers`, `get_chamfer`, `create_chamfer`, `remove_chamfer` | `Edge` (`ensure_*` 없음) |
| Shell | `shells`, `get_shell`, `create_shell`, `remove_shell` | `Face` (`ensure_*` 없음) |
| Thickness | `thicknesses`, `get_thickness`, `create_thickness`, `remove_thickness` | `Face` (`ensure_*` 없음) |
| Hole | `holes`, `get_hole`, `create_hole`, `remove_hole` | `Face` (`ensure_*` 없음) |

회전 feature는 다음처럼 각도를 조절할 수 있습니다.

```python
shaft = design.get_shaft("REVOLVE")
shaft.set_first_angle(180, unit="deg")
shaft.set_second_angle(0, unit="deg")
part.update()
```

Rib와 Slot은 profile과 path 두 `Sketch` wrapper를 받습니다. 각 스케치의 COM 객체를
`AddNewRib`/`AddNewSlot`에 넘기는 일은 SDK가 내부에서 합니다. 같은 이름의
기존 feature가 있는 경우 `ensure_*`가 profile identity를 확인합니다. CATIA가
path를 안정적으로 되돌려 주지 않는 제한 때문에 path의 동일성은 비교하지
않습니다.

### 사각 패턴

사각 패턴은 현재 verified call form을 감싼 생성 API만 제공합니다. 방향은
중복된 reverse flag 대신 signed axis로 지정합니다.

```python
from auto_3dx import PartUpdateError

pattern = design.create_rectangular_pattern(
    pad,
    number_in_direction_1=2,
    number_in_direction_2=3,
    spacing_in_direction_1=100,
    spacing_in_direction_2=80,
    direction_1="X",
    direction_2="Y",
)
try:
    part.update()
except PartUpdateError:
    design.remove_rectangular_pattern(pattern)
    part.update()
    raise
```

두 방향이 같은 축이면 COM 호출 전에 거부합니다. 이름 기반 pattern 조회·ensure는
아직 제공하지 않습니다. 생성 후 update가 실패하면 반환된 wrapper를
`remove_rectangular_pattern(pattern)`에 전달해 Selection 경로로 정리할 수
있습니다. 이 create → update → cleanup 경로는 B428_Cloud live integration으로
검증했습니다.

### 모서리 필렛과 챔퍼

면·모서리를 지목할 수 없어 막혀 있던 약 80개 face/edge feature 중 첫 두 개가
`create_edge_fillet`/`create_chamfer`로 구현되었습니다. 모서리는 이름이나
좌표가 아니라 `part.topology.edges()`가 돌려주는 `EdgeSnapshot`
에서 얻습니다. 이 snapshot은 스케치가 아니라 **솔리드 전체**의 모서리를
검색한 결과이고, 한 feature의 모서리만 골라 검색 범위를 좁히는 방법은 없습니다.

```python
snapshot = part.topology.edges()

fillet = design.create_edge_fillet("F1", snapshot[0], radius=3, unit="mm")
part.update()

chamfer = design.create_chamfer(
    "C1", snapshot[1],
    length1=1.5, length2_or_angle=45,
    propagation=0, orientation=0,
)
part.update()
```

반드시 알아야 할 제약이 세 가지 있습니다.

- **모서리를 재빌드 너머로 지목하는 방법이 없습니다.** `Edge.descriptor`가 주는
  BRep 이름 문자열을 저장했다가 나중에 같은 모서리로 되돌리는 경로,
  재빌드 후 이름·순서를 보존하는 경로, 측정으로 모서리를 고르는 경로, 검색
  범위를 한 feature로 좁히는 경로, 이 네 가지를 모두 시도했고 전부 막혔습니다.
  `Edge.index`는 그 snapshot을 만든 순간의 모델에서만 의미가 있습니다.
- **모델이 바뀌면 이전 snapshot은 거부됩니다.** 같은 snapshot으로 필렛을 두 번
  만들면 성공할 때도 실패할 때도 있고, 호출자는 미리 알 수 없습니다. 그래서
  `Part`는 하나의 model generation 카운터를 갖고, 이 Part로부터 얻은 모든
  collection과 wrapper가 그 카운터를 공유합니다. feature 생성·삭제·이름변경,
  파라미터·제약 값 쓰기, formula 변경, `sketch.edit()` 세션을 닫는 것,
  `part.update()`(성공/실패 무관) 등 **COM에 mutation을 시도하는 모든 경로**가
  카운터를 올립니다. `list`/`get`/측정/snapshot 같은 읽기 전용 호출과, COM 호출
  전에 거부된 요청은 올리지 않습니다. 파라미터 값은 그 파라미터가 아무것도
  구동하지 않아도 카운터를 올립니다 — 그 파라미터가 formula를 거쳐 치수를
  구동하는지 SDK가 알 수 없기 때문입니다. 이 카운터가 스냅샷을 뜬 시점보다
  올라가 있으면, 그 스냅샷의 `Edge`/`Face`를 쓰는 순간 COM에 닿기 전에
  `StaleSnapshotError`를 냅니다.

  ```python
  from auto_3dx.errors import StaleSnapshotError

  try:
      design.create_edge_fillet("F2", snapshot[1], radius=2, unit="mm")
  except StaleSnapshotError:
      snapshot = part.topology.edges()  # 새로 떠야 한다
  ```

  **3DEXPERIENCE UI나 다른 스크립트로 만든 변경은 이 카운터에 보이지 않습니다.**
  스냅샷은 쓰기 직전에 새로 떠야 합니다.
- **`ensure_edge_fillet`/`ensure_chamfer`는 없습니다.** `ensure_pad`처럼 기존
  feature의 소스를 비교하려면 안정적으로 다시 읽을 수 있는 핸들이 필요한데
  모서리에는 그런 핸들이 없습니다. 잘못된 모서리를 조용히 재사용하는 것보다
  메서드가 없는 편이 낫습니다.

챔퍼의 `mode`는 인자로 노출하지 않습니다. 검증된 세 값 중 1만 생성과 update
모두 성공해서(0은 update 실패, 2는 생성 자체가 실패) 내부에 고정했습니다.
`propagation`/`orientation`은 CATIA type library에 뜻이 문서화되어 있지 않아
검증된 정수 값만 상수(`CHAMFER_PROPAGATION_0`/`_1`, `CHAMFER_ORIENTATION_0`/`_1`,
`auto_3dx.geometry.part_design`)로 제공합니다.

필렛/챔퍼 모두 `create_*` 뒤 update가 실패하면 그 feature가 트리에 남고,
**지우기 전까지 이후의 모든 `Part.Update()`가 실패합니다.**
`remove_edge_fillet(name)`/`remove_chamfer(name)`으로 지운 뒤에 재시도해야
합니다.

### Shell, Thickness, Hole (면 참조)

모서리와 같은 참조 경로가 면에도 통합니다. `part.topology.faces()`가 돌려주는
`FaceSnapshot`에서 `Face`를 얻어 `create_shell`/`create_thickness`/`create_hole`에
넘깁니다.

```python
faces = part.topology.faces()

shell = design.create_shell("S1", faces[0], internal_thickness=2.0, external_thickness=0.0)
part.update()

thickness = design.create_thickness("T1", faces[1], offset=3.0)
part.update()

hole = design.create_hole("H1", faces[2], depth=5.0)
part.update()
```

검증된 값은 shell `(internal_thickness=2.0, external_thickness=0.0)`,
thickness `offset=3.0`, hole `depth=5.0`이며 각각 첫 면 하나에서 생성과
`Part.Update()`를 확인했습니다. `internal_thickness`/`offset`/`depth`는 양수만
받고, `external_thickness`만 검증된 경계값이 `0.0`이라 0 이상을 허용합니다.

면 snapshot도 모서리와 같은 model generation을 공유하므로 모델이 바뀌면 stale이
되어 COM 전에 `StaleSnapshotError`를 냅니다. 다만 모서리에서 확인한 것처럼 같은
snapshot의 재사용 실패를 반복 실험으로 재현하지는 않았습니다. 면마다 새 검색으로
한 번씩만 확인했고, 같은 `Reference` 메커니즘이라 같은 규칙을 보수적 기본값으로
적용했습니다. `ensure_shell`/`ensure_thickness`/`ensure_hole`은 없습니다. 면에는
기존 feature와 비교할 안정적인 핸들이 없기 때문입니다.

## 측정

`part.measurement`는 Part가 속한 Editor의 CATIA 측정 서비스에 연결된
read-only wrapper입니다. 인자 없이 호출하면 Part의 main body를 잽니다.

```python
properties = part.measurement.measure()
print(properties.volume_mm3)
print(properties.area_mm2)
print(properties.mass_kg)
print(properties.cog_mm)
```

다른 대상을 재려면 여전히 raw CATIA 객체를 넘길 수 있습니다.

```python
properties = part.measurement.measure(part.com_object.MainBody)
```

기본 대상은 측정 시점마다 다시 읽으므로, 측정 객체를 만든 뒤 main body가 바뀌어도
새 body를 잽니다. 기본 대상도 없고 인자도 없으면 COM 호출 전에 `ValidationError`를
냅니다. `SolidMeasurement.com_object`가 다른 wrapper와 같은 이름의 escape hatch이고,
`editor_com_object`는 `DeprecationWarning`을 내는 alias로 1.0 전에 제거합니다.

`MassProperties`의 public 단위는 `mm³`, `mm²`, `kg`, `mm`입니다. CATIA 측정
서비스가 반환하는 SI 길이·면적·부피를 각각 변환하며 질량은 kg로 유지합니다.

bounding box는 제공하지 않습니다. `InertiaBoxService`가 있고 한 세션에서는 실제
값을 돌려줬지만, 같은 모델에서 다른 세션에서는 전부 0을 반환했습니다. 실패도 아니고
0을 돌려주는 측정은 없는 것보다 위험하므로 공개 API에서 제외했습니다.

측정은 `Update()`, `Save()`, `PLMPropagate()`를 호출하지 않습니다.

## 모델 검사

모델을 바꾸기 전에 무엇이 들어 있는지 읽습니다. 결과는 COM 객체가 아니라 frozen
dataclass이고, 검사는 모델 generation, selection, In-Work Object를 바꾸지 않습니다.

```python
summary = part.inspect.summary()
print(summary.render())

summary.features          # FeatureInfo(name, kind, supported), main body, 트리 순서
summary.sketches          # main body 스케치 이름
summary.parameters        # 사용자 파라미터
summary.bodies            # BodyInfo(name, is_main, features, sketches)
summary.geometrical_sets  # GeometricalSetInfo(name, elements, nested_set_count)
summary.topology          # TopologyCounts(edges, faces), selection이 없는 Part면 None
summary.in_work_object    # InWorkObjectInfo(name, kind, is_main_body), 없으면 None

iwo = part.inspect.in_work_object()
if iwo is not None and not iwo.is_main_body:
    print(f"In-Work Object가 main body가 아닙니다: {iwo.name} ({iwo.kind})")
```

In-Work Object는 CATIA가 다음 feature를 넣는 위치입니다. `kind`는 CATIA wrapper 타입
이름(`"Body"`, `"Pad"` 등)이고, `is_main_body`는 이름이 아니라 COM 동일성으로 판단합니다.
live에서 pad를 만들면 새 pad가 In-Work Object가 되었고, 평면을 만들면 main body로
돌아왔습니다. feature를 지워도 이전 In-Work Object로 돌아가지는 않습니다. 확인할 때
`part.com_object.InWorkObject`를 직접 읽을 필요가 없습니다.

## 변경과 저장의 안전 규칙

이 라이브러리는 현재 CATIA 세션의 모델을 변경할 수 있지만 서버 저장까지
자동화하지 않습니다.

- Parameter·Formula·Sketch·Part Design 메서드는 암묵적으로 `Part.Update()`를
  호출하지 않습니다.
- 필요한 변경을 모두 적용한 뒤 호출자가 `part.update()`를 명시적으로
  호출해야 합니다.
- 라이브러리의 어떤 경로도 `Save()` 또는 `PLMPropagate()`를 호출하지 않습니다.
- 저장이 필요하면 결과와 모델 상태를 직접 확인한 뒤 3DEXPERIENCE UI에서
  사용자가 저장해야 합니다.
- 생성·삭제·값 변경은 현재 세션의 unsaved 상태를 즉시 바꿀 수 있습니다.
  테스트용 이름을 사용하고, 필요하면 삭제와 원상복구를 직접 수행해야 합니다.

`Part.Update()`가 성공했다는 사실만으로 형상이 의도대로 만들어졌다고 보장할
수는 없습니다. 필요한 경우 측정 결과나 모델 조회로 별도 검증해야 합니다.

## 현재 제한 사항

### 새 PLM Part 생성

`Catia.create_part()`나 `PLMCreate()`를 공개 API로 제공하지 않습니다. 현재
Automation 경로의 PLM Physical Product/3D Shape 생성은 설치 환경에서
라이선스·서비스 제약으로 안정적으로 검증되지 않았습니다. 따라서 자동화 전에
3DEXPERIENCE UI에서 Physical Product와 3D Shape/Part를 생성하고 열어 두어야
합니다. 생성된 Part의 Parameter·Sketch·Part Design 편집은 지원 범위 안에서
수행할 수 있습니다.

### BRep 의존 feature

면·모서리 참조가 필요한 feature 중 `EdgeFillet`/`Chamfer`(모서리 참조)와
`Shell`/`Thickness`/`Hole`(면 참조)을 제공합니다.
`Selection.Search('Topology.Edge,all')` / `('Topology.Face,all')` +
`SelectedElement.Reference`로 모서리·면 `Reference`를 얻는 경로가 뚫렸을 뿐이고,
그 모서리·면을 재빌드 너머로 다시 지목하는 방법은 없습니다(`part.topology.edges()`
/ `part.topology.faces()`를 다시 불러야 합니다). `Draft`처럼 나머지 면 reference
feature는 아직 제공하지 않습니다.

Stiffener, CircPattern, UserPattern 등은 `AddNew*`가 객체를 반환하더라도
follow-up `Part.Update()`에서 실패한 사례가 있어 검증된 API로 승격하지
않았습니다. GSD surface(평면 생성에 쓰는 것 외의 HybridShape), assembly
constraint, 축 시스템, 다른 Body/HybridBody도 현재 public wrapper 범위
밖입니다.

## 테스트

`pyproject.toml`은 `integration` marker를 등록하고 기본 실행에서 통합
테스트를 제외합니다. 테스트 도구는 `test` extra로 설치합니다.

```powershell
python -m pip install -e ".[test]"
```

CATIA 없이 실행하는 단위 테스트:

```powershell
python -m pytest tests/unit -q
```

실행 중인 3DEXPERIENCE가 필요한 통합 테스트:

```powershell
python -m pytest tests/integration -m integration -q
```

통합 테스트는 세션이 없거나 필요한 객체를 찾지 못하면 실패 대신 skip할 수
있습니다. 일부 테스트는 현재 세션에 임시 geometry/parameter를 만들었다가
정리하므로, 저장하지 않은 별도 작업 세션에서 실행하는 것이 좋습니다. 테스트와
라이브러리 모두 `Save()`와 `PLMPropagate()`를 호출하지 않습니다.

통합 테스트 세션은 시작할 때 사용자의 CATIA selection을 저장하고 비운 뒤, 끝날 때
되돌리고 개수로 확인합니다(`tests/integration/conftest.py`). `remove_*`가 selection을
거쳐 지우므로 이 장치가 없으면 실행 뒤 selection이 비어 있었습니다.

단위 테스트는 가짜 COM 객체만 쓰고 3DEXPERIENCE, 레지스트리의 com3dx 항목, `com3dx`를
건드리지 않으므로 3DEXPERIENCE가 없는 Windows에서도 실행됩니다.
`.github/workflows/unit-tests.yml`은 새 checkout에서 `pip install ".[test]"` 후 Windows
CPython 3.11–3.14로 단위 테스트를 실행합니다. live 통합 테스트는 CI에 넣지 않습니다.

현재 결과는 위 "검증된 Python 환경" 표와 같습니다. 단위 테스트는 868개입니다. B428_Cloud
live 통합 테스트는 40개이고, 열려 있는 Part에 수동으로 파라미터를 추가해 두지 않았다면 그
중 1건은 skip됩니다. 최근 실행한 Part에는 그 파라미터가 있어 40개가 모두 통과했습니다. 통합 검증 범위는 설치된 3DEXPERIENCE 세션과 현재 모델에 따라
달라집니다.

## 저장소 문서

- [기능 현황](docs/capabilities.md) — 기능별 지원·미지원 상태
- [개발 상태와 결정 기록](docs/status.md) — 검증 결과, 열린 문제, 설계 결정
- [COM/API 컨벤션](docs/conventions.md) — 실측된 COM 사실과 public API 계약
- [PLM object 생성 조사](docs/plm_object_creation.md) — 새 Part 생성이 막힌 경위
- [공개 API 예제](examples/build_part.py) — 기존 Part를 Parameter와 Pad로 수정하는 예제

`scripts/probes/`에는 공개 API로 승격하기 전의 설치본·type library·실행 세션
조사 프로그램이 있습니다. probe에서 `AddNew*`가 객체를 반환한 것만으로는
지원 기능으로 간주하지 않으며, 필요한 경우 `Part.Update()`까지 성공한 동작만
라이브러리 계약에 포함합니다.
