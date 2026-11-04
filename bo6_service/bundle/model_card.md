# Model card — E03_efficientnet_b0 (dressme-v0.2)

**Status: exported ML prototype, production validation pending.**

## Classifier
- efficientnet_b0, pretrained source `torchvision:EfficientNet_B0_Weights.IMAGENET1K_V1`; head trained, then last blocks fine-tuned.
- Data: Fashion Product Images (Kaggle), Apparel subset; 10795 train / 2310 validation / 2336 reserved test rows; split fingerprint `f7f11d3ef7d2963e`.
- Catalog validation: macro-F1 0.8882, accuracy 0.9316, top-2 accuracy 0.9922; majority-class baseline macro-F1 0.0572.
- Selection: highest validation macro-F1, then lowest CPU latency within 0.01 macro-F1. Seed stability: {"status": "measured", "experiment": "E01_resnet18", "seed_a": 42, "macro_f1_a": 0.8922930518153332, "seed_b": 43, "macro_f1_b": 0.8757216572818074, "abs_difference": 0.01657139453352585}.
- Review policy: threshold 0.7, always_review True — threshold measured on CATALOG validation only; scores are uncalibrated softmax; not validated on phone photos, so always_review stays True.

### Weakest classes on validation
| class | precision | recall | F1 | support |
|---|---|---|---|---|
| sweatshirt | 0.685 | 0.881 | 0.771 | 42 |
| sweater | 0.842 | 0.762 | 0.800 | 42 |
| top | 0.788 | 0.817 | 0.802 | 263 |
| skirt | 1.000 | 0.714 | 0.833 | 21 |

## Attribute heads (weak labels)
Linear heads on the classifier's pooled features plus a 512-bin RGB histogram, standardised with training statistics. Labels come from catalog metadata (`baseColour`, `articleAttributes`). Missing labels stay missing; unsupported values (e.g. three-quarter sleeves, rare patterns) are excluded. Details and mappings: `attribute_card.json`.

- **sleeve_length** — policy: stated if score >= 0.0. Eligible garment types: jacket, shirt, sweatshirt, t-shirt, top. On the 1639 eligible, catalog-labelled validation rows: accuracy 0.9274, macro-F1 0.8718 (majority baseline 0.6760); answered at the policy threshold 1.000 of those rows with error 0.0726. Across all 2310 validation images with predicted categories: stated 1787, below threshold or suggestion-only 0, inapplicable garment type 417, category withheld 106.
- **pattern** — policy: stated if score >= 0.97. Eligible garment types: dress, jacket, shirt, shorts, skirt, sweatshirt, t-shirt, top, trousers. On the 1835 eligible, catalog-labelled validation rows: accuracy 0.8267, macro-F1 0.8108 (majority baseline 0.4267); answered at the policy threshold 0.725 of those rows with error 0.0932. Across all 2310 validation images with predicted categories: stated 1515, below threshold or suggestion-only 569, inapplicable garment type 120, category withheld 106.
- **color** — policy: suggestion only. Eligible garment types: dress, jacket, jeans, shirt, shorts, skirt, sweater, sweatshirt, t-shirt, top, trousers. On the 2291 eligible, catalog-labelled validation rows: accuracy 0.6905, macro-F1 0.6427 (majority baseline 0.1742); answered at the policy threshold 0.000 of those rows with error n/a. Across all 2310 validation images with predicted categories: stated 0, below threshold or suggestion-only 2204, inapplicable garment type 0, category withheld 106.

The thresholds were explored on the same validation rows used to report them, so the error at the threshold is optimistic. The sleeve threshold is a provisional reviewed-demo policy: every description is shown to the user.

## Leakage and split
- PROVISIONAL: exact SHA-256 copies never cross splits; near-duplicates are measured, not removed (457 near-identical and 17588 similar-pixel pairs cross splits; search coverage partial).
- Sensitivity check (validation rows without a pixel-similar training image vs all): all: n=2310, acc 0.9316, macro-F1 0.8882; near-identical (MAD <= 3.0): linked to a training image: n=37, acc 0.9730, macro-F1 0.4498; near-identical (MAD <= 3.0): NOT linked: n=2273, acc 0.9309, macro-F1 0.8879; similar (MAD <= 8.0): linked to a training image: n=638, acc 0.9561, macro-F1 0.8644; similar (MAD <= 8.0): NOT linked: n=1672, acc 0.9222, macro-F1 0.8788
- Product identity is not established by any automatic check; near-duplicate risk is reduced, not eliminated.
- Taxonomy is provisional (mapped from catalog label strings, no human visual review).

## Evaluation gaps
- Final catalog test: not run (reserved split closed).
- Real phone photos: absent (development), absent (final).
- Description factuality: no human review completed.
- Scores are uncalibrated softmax values.
