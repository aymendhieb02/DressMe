# DressMe BO6 — garment classification and description bundle

**Status: exported ML prototype, production validation pending.**

## Problem
Typing every garment into a digital wardrobe is slow. BO6 turns one garment photo into a suggested category and a short structured description that the user reviews and corrects before saving.

## What is implemented
1. Category classification: efficientnet_b0 fine-tuned from ImageNet, 11 classes (dress, jacket, jeans, shirt, shorts, skirt, sweater, sweatshirt, t-shirt, top, trousers), top-2 suggestions with uncalibrated scores.
2. Description: a deterministic template over structured fields (category, sleeve length, pattern). It is **not** produced by a generative language model.
3. Colour: two suggestions for the user to confirm. Colour is never written into the sentence until the user confirms it.
4. Every prediction is flagged for user review.

## Which interface to use
- **`attributes.GarmentDescriber`** — the entry point for the application. Category, description with sleeve/pattern, colour suggestions.
- `inference.GarmentClassifier` — category-only fallback (works without `attribute_heads.pt`).

```python
from attributes import GarmentDescriber
model = GarmentDescriber()            # CPU, no network access
result = model.predict('photo.jpg')    # path or PIL.Image
result = model.predict('photo.jpg', confirmed={'color': 'blue'})   # after the user corrects a field
```

## Installation assumptions
Python with the versions in `requirements.txt` (torch 2.11.0+cu128, torchvision 0.26.0+cu128). Keep all files of this folder together. Run `python selftest.py` after installing: it checks the code paths in a fresh process and must print `"passed": true`. An unreadable image raises `ValueError`.

## Input and output
Input: one photo of one mostly visible garment. Output (real output of this bundle for one validation image; the image itself is not shipped):

```json
{
  "image": "39386.jpg",
  "category": "jeans",
  "score": 0.9999536275863647,
  "score_type": "uncalibrated_softmax",
  "suggestions": [
    {
      "category": "jeans",
      "score": 0.9999536275863647
    },
    {
      "category": "trousers",
      "score": 4.396647636895068e-05
    }
  ],
  "category_confident": true,
  "needs_user_review": true,
  "model_version": "E03_efficientnet_b0",
  "taxonomy_version": "dressme-v0.2",
  "description": "A pair of jeans.",
  "description_fields": {
    "category": "jeans",
    "color": "unknown",
    "pattern": "unknown",
    "sleeve_length": "unknown"
  },
  "description_provenance": {
    "category": "classifier",
    "color": "not_estimated",
    "pattern": "not_estimated",
    "sleeve_length": "not_estimated"
  },
  "description_version": "tmpl-v0.4-attributes",
  "attributes": {
    "sleeve_length": {
      "eligible": false,
      "reason": "not applicable to 'jeans'",
      "threshold": 0.0,
      "score_type": "uncalibrated_softmax",
      "suggestions": [],
      "value": "unknown",
      "source": "not_estimated",
      "stated_in_description": false
    },
    "pattern": {
      "eligible": false,
      "reason": "not applicable to 'jeans'",
      "threshold": 0.97,
      "score_type": "uncalibrated_softmax",
      "suggestions": [],
      "value": "unknown",
      "source": "not_estimated",
      "stated_in_description": false
    },
    "color": {
      "eligible": true,
      "reason": null,
      "threshold": null,
      "score_type": "uncalibrated_softmax",
      "suggestions": [
        {
          "value": "blue",
          "score": 0.9981210827827454
        },
        {
          "value": "navy",
          "score": 0.0016561899101361632
        }
      ],
      "value": "unknown",
      "source": "not_estimated",
      "stated_in_description": false
    }
  },
  "color_suggestions": [
    {
      "value": "blue",
      "score": 0.9981210827827454
    },
    {
      "value": "navy",
      "score": 0.0016561899101361632
    }
  ],
  "interface": "GarmentDescriber (category + attributes)"
}
```

- `score` and every attribute score are raw softmax values, **not calibrated probabilities**.
- `attributes.<name>.eligible = false` means the attribute is not predicted for that garment type; no value or suggestion is returned.
- `description_provenance` says where each field came from: `classifier`, `attribute_model`, `user_confirmed`, `withheld_low_score` or `not_estimated`.

## Limitations
- Trained and validated on catalog photos (mostly worn by models, plain backgrounds). No phone-photo evaluation exists.
- A garment outside the supported classes is still forced into one of them.
- Attribute accuracy is agreement with weak catalog labels, not human-verified truth. See `model_card.md`.
- Not included: multi-garment detection, segmentation, label OCR, a review UI or wardrobe storage.

## Optional: image quality assistant

```python
from quality_checks import check_image
report = check_image('photo.jpg')   # warnings + suggested actions
```

Rule-based warnings (small, blurry, dark, washed out, low contrast). Advisory only: it never blocks a prediction, and a clean report does not mean the garment is fully visible or that the prediction is right. Thresholds in `quality_config.json` are provisional and were not validated on phone photos.
