# auto-3dx

`auto-3dx`는 외부 Python 프로세스에서 Windows COM을 통해 실행 중인
3DEXPERIENCE CATIA 세션에 연결하고, 열려 있는 Part를 자동화하는 Python
라이브러리입니다.

현재 공개 API는 다음 작업을 지원합니다.

- 실행 중인 3DEXPERIENCE 세션 attach
- 열린 Editor와 Part 선택
- 사용자 Parameter 생성·조회·변경
- Formula 생성·조회·변경
- Sketch와 2D 프로파일 생성
- Sketch constraint 지정
- Pad, Pocket, Shaft, Groove, Mirror, Rib, Slot 생성
- 사각 패턴 생성 API
- 솔리드의 부피·면적·질량·무게중심 측정

Part 자체의 PLM 생성과 저장은 이 라이브러리의 책임 범위가 아닙니다. 먼저
3DEXPERIENCE에서 Part를 만들고 열어 둔 뒤 `auto-3dx`를 사용해야 합니다.

## 요구 사항

- Windows
- Python 3.11 이상
- 실행 중인 3DEXPERIENCE CATIA 세션
- 3DEXPERIENCE 설치본의 `com3dx.py`
- `pywin32` (패키지 설치 시 자동 설치)

현재 실제 검증 대상은 `B428_Cloud` 설치본입니다. 릴리스에 따라 Automation
object model이나 설치 경로가 달라질 수 있으므로, 다른 릴리스는 별도로
검증해야 합니다.

## 설치

저장소 루트에서 Python 3.11 이상의 환경을 활성화한 다음 editable install을
수행합니다.

```powershell
python -m pip install -e .
```

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
순서입니다.

```python
from pathlib import Path

catia = Catia.attach(
    Path(r"C:\Program Files\Dassault Systemes\B428_Cloud\win_b64\code\python3dx\lib\com3dx.py")
)
```

또는 PowerShell에서 다음처럼 지정할 수 있습니다.

```powershell
$env:AUTO_3DX_COM3DX_PATH = 'C:\Program Files\Dassault Systemes\B428_Cloud\win_b64\code\python3dx\lib\com3dx.py'
python .\your_script.py
```

같은 Python 프로세스에서 이미 다른 설치 릴리스의 `com3dx`가 로드된 경우에는
안전하게 교체하지 않고 오류를 발생시킵니다. 다른 릴리스를 사용하려면 새
Python 프로세스에서 시작해야 합니다.

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

Sketch 편집 제약은 반드시 같은 `with sketch.edit()` 블록 안에서, geometry
메서드가 반환한 raw 2D COM 객체를 사용해 지정해야 합니다.

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

회전 feature는 다음처럼 각도를 조절할 수 있습니다.

```python
shaft = design.get_shaft("REVOLVE")
shaft.set_first_angle(180, unit="deg")
shaft.set_second_angle(0, unit="deg")
part.update()
```

Rib와 Slot은 profile과 path 두 Sketch를 raw COM 객체로 전달합니다. 같은 이름의
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

## 측정

`part.measurement`는 Part가 속한 Editor의 CATIA 측정 서비스에 연결된
read-only wrapper입니다. 측정 대상은 raw CATIA 객체를 넘깁니다.

```python
solid = part.com_object.MainBody

properties = part.measurement.measure(solid)
print(properties.volume_mm3)
print(properties.area_mm2)
print(properties.mass_kg)
print(properties.cog_mm)

```

`MassProperties`의 public 단위는 `mm³`, `mm²`, `kg`, `mm`입니다. CATIA 측정
서비스가 반환하는 SI 길이·면적·부피를 각각 변환하며 질량은 kg로 유지합니다.

bounding box는 제공하지 않습니다. `InertiaBoxService`가 있고 한 세션에서는 실제
값을 돌려줬지만, 같은 모델에서 다른 세션에서는 전부 0을 반환했습니다. 실패도 아니고
0을 돌려주는 측정은 없는 것보다 위험하므로 공개 API에서 제외했습니다.

측정은 `Update()`, `Save()`, `PLMPropagate()`를 호출하지 않습니다.

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

면·모서리 같은 안정적인 BRep reference가 필요한 Chamfer, EdgeFillet, Hole,
Draft, Shell, Thickness 등의 API는 아직 제공하지 않습니다. feature 전체를
넘기는 것만으로는 CATIA가 요구하는 면·모서리 reference를 만들 수 없고, 모델
변경 시 문자열 BRep 이름도 깨질 수 있기 때문입니다.

Stiffener, CircPattern, UserPattern 등은 `AddNew*`가 객체를 반환하더라도
follow-up `Part.Update()`에서 실패한 사례가 있어 검증된 API로 승격하지
않았습니다. GSD surface, HybridShape, assembly constraint, 축 시스템,
다른 Body/HybridBody도 현재 public wrapper 범위 밖입니다.

사용자 정의 offset plane 위 Sketch는 일부 동작이 확인되었지만, 그 Sketch를
사용한 Pad까지 안정적으로 검증된 상태는 아닙니다.

## 테스트

`pyproject.toml`은 `integration` marker를 등록하고 기본 실행에서 통합
테스트를 제외합니다. 개발 환경에 pytest가 없다면 먼저 설치합니다.

```powershell
python -m pip install pytest
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

현재 fake-COM 단위 테스트 414개와 B428_Cloud live 통합 테스트 27개가
통과했습니다. 통합 검증 범위는 설치된 3DEXPERIENCE 세션과 현재 모델에 따라
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
