# agent_skill

Claude Code용 스킬 모음입니다.

| 스킬 | 설명 | 출처 |
|---|---|---|
| [confidence](confidence/) | 답변의 핵심 주장과 최종 답변에 확신도 `P(Y)`를 붙이고, 기록으로 보정 상태(ECE/Brier)를 측정합니다. | 자체 제작 |
| [discernment-nudge](discernment-nudge/) | 조언·추정·분석 답변 뒤에 사실·가정·빠진 맥락을 점검하는 후속 질문 2~3개를 붙입니다. confidence와 함께 쓰기 좋습니다. | Anthropic (Apache 2.0) |
| [skill-creator](skill-creator/) | 스킬을 만들고 고치며, eval로 성능을 측정합니다. | Anthropic (Apache 2.0) |
| [doc-coauthoring](doc-coauthoring/) | 제안서·기술 스펙·의사결정 문서를 단계별로 함께 작성합니다. (링크만 제공) | Anthropic |

## 설치

원하는 스킬 폴더를 `~/.claude/skills/` 아래에 복사합니다. 스킬별 상세 설명은 각 폴더의 `README.md` 또는 `SKILL.md`를 참고하세요.

## 서드파티 스킬

`discernment-nudge`, `skill-creator`는 [anthropics/skills](https://github.com/anthropics/skills) 커밋 `ca45fc4`(2026-10-28)의 원본을 수정 없이 가져왔습니다. 각 폴더의 `LICENSE.txt`(Apache License 2.0)를 따릅니다.
