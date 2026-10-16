# A/B 실험 보고서

원본은 C의 [ab_test.json](results/ab_test.json), [검증 결과](results/experiments/C/ab_verification_dev.json)다.
B11은 수치를 읽고 분모/통계/해시를 재확인하며 원본을 덮어쓰지 않는다.

## 실험 설계

seed 42, dev 합성 데이터. 사용자 단위 무작위 배정으로 control/treatment 각 200명,
30일·매일 top10이다. control은 train popularity, treatment는 full pipeline이다.
반복 노출은 사용자 내 군집이며 독립 시행으로 간주하지 않는다. train+valid 이력만 사용하고 test 결과를 읽지 않는다.
MAB는 사용자별 B5 메모리 adapter로 격리했다. 라이브 Redis 공용 bandit 실험이 아니다.

## 분모와 수식

CTR = clicks/impressions, CVR = purchases/impressions, purchase_given_click = purchases/clicks다.
상대 lift = treatment/control − 1. 같은 사용자에서 반복된 노출은 사용자 군집 delta variance로 CI를 계산한다.
각 arm의 r=Σc_i/Σd_i, Var(r)=n/(n−1)·Σ(c_i−r·d_i)²/(Σd_i)²,
차이의 SE=√(Var_control+Var_treatment), 95% CI=(r_t−r_c)±1.96·SE다.
별도의 독립 사용자 지표는 사용자당 한 번의 구매 여부이며 p_a=구매 사용자/n_a,
pooled p=(x_c+x_t)/(n_c+n_t), z=(p_t−p_c)/√[p(1−p)(1/n_c+1/n_t)],
양측 p-value=2Φ(−|z|)다. Pearson χ²는 같은 사용자 2×2 표에서 계산한다.
희소/경계 셀에서는 근사 신뢰성을 표시하고 Fisher 검정을 별도 보고한다.

## 실제 결과

| 항목 | control | treatment |
|---|---:|---:|
| users | 200 | 200 |
| impressions | 60000 | 60000 |
| clicks | 14870 | 11926 |
| purchases | 691 | 540 |
| explorations | 0 | 12000 |
| ctr | 0.24783333333333332 | 0.19876666666666667 |
| cvr | 0.011516666666666666 | 0.009 |
| purchase_given_click | 0.0464694014794889 | 0.045279221868187156 |
| users_purchased | 182 | 174 |

| 지표 | 상대 lift | 차이 | 95% CI(차이) | 양측 p-value |
|---|---:|---:|---|---:|
| ctr (사용자 군집) | -19.7983% | -0.04906667 | [-0.05664514, -0.04148819] | 6.7404699e-37 |
| cvr (사용자 군집) | -21.8524% | -0.00251667 | [-0.00404274, -0.00099060] | 0.0012283834 |
| 한 번 이상 구매한 사용자 | -4.3956% | -0.04000000 | [-0.10119986, 0.02119986] | 0.20110647 |

구매 사용자 χ²=1.63432074, p=0.20110647. 클릭 사용자 비율은 양 arm 모두 1로 경계값이며 z=0, p=1, 근사 신뢰성 false다.

## 해석과 제한

treatment CTR/CVR은 control보다 낮았다. 독립 구매 사용자 위험 차이는 p≈0.201로 유의하지 않다.
군집 rate 통계와 사용자 위험 통계는 추정 대상이 다르며 유리한 것만 선택하지 않는다.
최적화한 offline Recall/NDCG와 합성 online CTR/CVR은 지표·상호작용·반응 모델이 달라 일치하지 않는다.
full pipeline의 제약/탐색과 합성 반응 모델을 고려해야 하며, 이 결과만으로 실제 사용자의 인과 효과를 주장하지 않는다.
과제 PDF p.5는 두 전략과 통계 검정을 요구한다. p.12의 5,000명/그룹·양의 lift·예시 p-value는 필수 성공 기준이 아니다.
현 dev 실험의 양의 lift를 만들기 위해 반응 확률이나 test 정답을 바꾸지 않았다.
full 모델·라이브 Redis MAB 연결 후의 A/B 통계는 **미측정**이다.
상세 근거 source SHA는 final_submission 및 final_acceptance.json에 포함한다.
