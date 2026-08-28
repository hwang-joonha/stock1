// 재무모델링 디자인 토큰 — 단일 출처
//
// model.html의 셸(var T)과 MODEL 노드의 색상(bg/fg/sfg/bdr/c)이 모두 이 값에서
// 나온다. 임의 hex를 새로 만들지 않는다. 색을 바꾸려면 여기만 고친다.
//
// 계열 규칙 (지키지 않으면 트리가 읽히지 않는다)
//   매출·수익 계열  → primary 램프 (파랑)
//   비용 계열       → neutral 램프 (회색)
//   입력(가정변수)  → primary.500 고정. 계산 노드와 한눈에 구분돼야 한다.
//   실적/추정 구분  → 색이 아니라 음영·투명도로. 색은 이미 계정 계층에 쓰였다.

const TOKENS = {
  primary: {
    900: '#1E2185',   // 루트 계정
    700: '#3332D0',   // 1단계 계정
    500: '#5D68F7',   // 입력 노드 · 강조
    400: '#7C91FD',
    300: '#A1B8FF',
    200: '#C5D5FF',
    100: '#DFE8FF',
    50:  '#EDF3FF',   // 추정 연도 셀 음영
  },

  neutral: {
    900: '#111827',
    800: '#1F2937',
    700: '#374151',   // 비용 루트
    600: '#4B5563',   // 본문
    500: '#6B7280',   // 비용 하위 · 보조 텍스트
    400: '#9CA3AF',   // 흐린 텍스트
    300: '#D1D5DB',
    200: '#E5E7EB',
    100: '#F3F4F6',
    50:  '#F9FAFB',
  },

  semantic: {
    revenue:    '#1E2185',
    revenueSub: '#3332D0',
    cost:       '#374151',
    costSub:    '#6B7280',
    profit:     '#22C55E',
    positive:   '#22C55E',
    negative:   '#DC2626',
    input:      '#5D68F7',
  },

  surface: {
    bg:      '#FFFFFF',
    surface: '#F8F8FA',
    border:  '#E5E5E8',
    // 사이드바는 어두운 면. 본문과 대비를 만들어 탐색과 내용을 분리한다.
    sidebarBg:     '#0F0F12',
    sidebarCard:   '#1A1A1F',
    sidebarBorder: '#2A2A2F',
  },

  text: {
    primary:   '#0F0F12',
    body:      '#4B5563',
    secondary: '#6B7280',
    muted:     '#9CA3AF',
  },

  // 계열 팔레트 — 형제 노드에 순서대로 배정한다.
  // 매출 계열과 비용 계열의 램프를 절대 섞지 않는다.
  ramp: {
    revenue: ['#1E2185', '#3332D0', '#5D68F7', '#7C91FD',
              '#A1B8FF', '#C5D5FF', '#282CA8', '#4B4DED'],
    cost:    ['#374151', '#4B5563', '#6B7280', '#9CA3AF',
              '#1F2937', '#111827', '#D1D5DB', '#E5E7EB'],
  },

  font: {
    // 제목은 Outfit, 본문·숫자는 Pretendard. 숫자가 열을 이루는 표에서는
    // tabular-nums를 함께 건다.
    heading: "'Outfit', 'Pretendard', sans-serif",
    body:    "'Pretendard', -apple-system, sans-serif",
  },
};

if (typeof module !== 'undefined') module.exports = TOKENS;
