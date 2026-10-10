CLASSIFICATION_CASES = [
    {"id": "claim-01", "category": "명확한 주장", "expected": "주장", "text": "작품의 중심 갈등은 공동체의 침묵이 개인을 고립시킨다는 점을 드러낸다."},
    {"id": "claim-02", "category": "명확한 주장", "expected": "주장", "text": "화자의 선택은 두려움보다 책임을 우선하려는 태도를 나타낸다."},
    {"id": "claim-03", "category": "명확한 주장", "expected": "주장", "text": "이 소설은 기억이 정체성을 형성하는 핵심 조건이라고 말한다."},
    {"id": "claim-04", "category": "명확한 주장", "expected": "주장", "text": "주인공의 변화는 타인과의 연대가 회복의 출발점임을 강조한다."},
    {"id": "claim-05", "category": "명확한 주장", "expected": "주장", "text": "반복되는 어둠의 이미지는 인물의 불안이 지속되고 있음을 나타낸다."},
    {"id": "claim-06", "category": "명확한 주장", "expected": "주장", "text": "작가는 침묵을 개인의 약함이 아니라 사회 구조의 결과로 제시한다."},
    {"id": "claim-07", "category": "명확한 주장", "expected": "주장", "text": "결말의 열린 장면은 독자에게 도덕적 선택의 책임을 묻는 장치이다."},
    {"id": "claim-08", "category": "명확한 주장", "expected": "주장", "text": "두 인물의 대립은 세대 간 가치관의 충돌을 중심 주제로 만든다."},
    {"id": "claim-09", "category": "명확한 주장", "expected": "주장", "text": "서술자의 제한된 시선은 독자가 사건을 의심하게 만드는 핵심 장치다."},
    {"id": "claim-10", "category": "명확한 주장", "expected": "주장", "text": "공간의 변화는 주인공이 과거의 상처를 받아들이는 과정을 상징한다."},
    {"id": "evidence-01", "category": "명확한 근거", "expected": "근거", "text": "작품의 첫 장면에서 주인공은 친구의 부탁을 거절하고 혼자 떠난다."},
    {"id": "evidence-02", "category": "명확한 근거", "expected": "근거", "text": "본문에서 화자는 같은 질문을 세 차례 반복하여 불안을 드러낸다."},
    {"id": "evidence-03", "category": "명확한 근거", "expected": "근거", "text": "예를 들어 인물은 위험을 알면서도 이웃에게 문을 열어 준다."},
    {"id": "evidence-04", "category": "명확한 근거", "expected": "근거", "text": "인용된 편지에는 주인공이 자신의 잘못을 인정하는 문장이 나온다."},
    {"id": "evidence-05", "category": "명확한 근거", "expected": "근거", "text": "갈등이 심해진 뒤 인물의 대화가 짧아졌기 때문에 긴장이 드러난다."},
    {"id": "evidence-06", "category": "명확한 근거", "expected": "근거", "text": "마지막 장면에서 두 사람은 같은 장소에 있지만 서로 말을 건네지 않는다."},
    {"id": "evidence-07", "category": "명확한 근거", "expected": "근거", "text": "작품 속 반복되는 비의 묘사는 인물의 슬픔을 뒷받침하는 근거가 된다."},
    {"id": "evidence-08", "category": "명확한 근거", "expected": "근거", "text": "두 번째 문단에서 서술자는 사건의 원인을 이전 선택과 연결한다."},
    {"id": "evidence-09", "category": "명확한 근거", "expected": "근거", "text": "실제로 주인공은 약속을 지키기 위해 자신의 이익을 포기한다."},
    {"id": "evidence-10", "category": "명확한 근거", "expected": "근거", "text": "원문 인용에서 동일한 표현이 세 번 반복되어 강한 집착을 확인할 수 있다."},
    {"id": "ambiguous-01", "category": "애매한 문장", "expected": "분류되지 않음", "text": "그럴 수도 있다."},
    {"id": "ambiguous-02", "category": "애매한 문장", "expected": "분류되지 않음", "text": "여러 해석이 가능하다."},
    {"id": "ambiguous-03", "category": "애매한 문장", "expected": "분류되지 않음", "text": "이 장면은 중요하다."},
    {"id": "ambiguous-04", "category": "애매한 문장", "expected": "분류되지 않음", "text": "무엇이 옳은지는 분명하지 않다."},
    {"id": "ambiguous-05", "category": "애매한 문장", "expected": "분류되지 않음", "text": "인물은 떠난다."},
    {"id": "ambiguous-06", "category": "애매한 문장", "expected": "분류되지 않음", "text": "이 표현은 의미가 있을지도 모른다."},
    {"id": "ambiguous-07", "category": "애매한 문장", "expected": "분류되지 않음", "text": "독자마다 다르게 느낄 수 있다."},
    {"id": "ambiguous-08", "category": "애매한 문장", "expected": "분류되지 않음", "text": "아마도 그런 것 같다."},
    {"id": "ambiguous-09", "category": "애매한 문장", "expected": "분류되지 않음", "text": "사건의 원인은 하나로 정하기 어렵고 해석에 따라 달라질 수 있다."},
    {"id": "ambiguous-10", "category": "애매한 문장", "expected": "분류되지 않음", "text": "나는 이 부분을 더 살펴볼 필요가 있다고 생각한다."},
]


def _sentence(number, paragraph, role, text):
    return {"id": f"sentence-{number}", "number": number, "paragraph": paragraph, "role": role, "text": text, "start": 0, "end": len(text)}


LINK_CASES = [
    {
        "id": f"linked-{index:02d}",
        "expected": "연결",
        "sentences": [
            _sentence(1, 1, "주장", f"고립 장면은 인물 변화와 공동체 책임을 드러낸다 {index}."),
            _sentence(2, 1, "근거", f"실제로 고립 장면은 인물 변화와 공동체 책임을 구체적으로 보여 준다 {index}."),
            _sentence(3, 1, "설명", "이는 앞선 근거가 주장에 연결되는 이유를 설명한다."),
        ],
    }
    for index in range(1, 6)
] + [
    {
        "id": f"unlinked-{index:02d}",
        "expected": "비연결",
        "sentences": [
            _sentence(1, 1, "주장", f"고립된 인물의 선택은 공동체 책임을 드러낸다 {index}."),
            _sentence(5, 3, "근거", f"계절의 온도 측정값은 해안 지역의 강수량을 기록한다 {index}."),
        ],
    }
    for index in range(1, 6)
]


SPELLING_CASES = [
    {"id": "spelling-01", "text": "이제 준비를 할수 있다.", "expected": ["할수 있다"]},
    {"id": "spelling-02", "text": "몇일 동안 작품을 읽었다.", "expected": ["몇일"]},
    {"id": "spelling-03", "text": "사실을 외곡해서 전달했다.", "expected": ["외곡"]},
    {"id": "spelling-04", "text": "상징적으러 표현한 장면이다.", "expected": ["상징적으러"]},
    {"id": "spelling-05", "text": "작품은 인물의 내면을 들어냈다.", "expected": ["들어냈다"]},
    {"id": "spelling-06", "text": "작가는 주제를 들어내다.", "expected": ["들어내다"]},
    {"id": "spelling-07", "text": "교사로써 학생을 지도했다.", "expected": ["로써"]},
    {"id": "normal-01", "text": "이제 준비를 할 수 있다.", "expected": []},
    {"id": "normal-02", "text": "며칠 동안 작품을 읽었다.", "expected": []},
    {"id": "normal-03", "text": "사실을 왜곡하지 않고 전달했다.", "expected": []},
    {"id": "normal-04", "text": "상징적으로 표현한 장면이다.", "expected": []},
    {"id": "normal-05", "text": "창고에서 상자를 들어냈다.", "expected": []},
]
