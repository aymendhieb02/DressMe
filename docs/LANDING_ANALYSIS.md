# Landing page analysis

> **Outdated in part.** The issues below have been fixed in `static/landing/index.html`, which is now hand-written and tracked in Git. This analysis also says a build would install the React design; it would not, because `landing/index.html` never loads `landing/src/`.

Inspected on 5 November 2026 at `http://localhost:8002/`, at the in-app browser's approximately 676 px viewport. This is an analysis of the page being served, its source, and its relationship to the integrated application. It is not a desktop or physical-device acceptance test.

## What the visitor sees today

The root route in `api.py` serves `static/landing/index.html` when that file exists. The file currently served is a single, older HTML/CSS/JavaScript campaign page. It is different from the React/Vite source in `landing/src/LandingPage.tsx`.

The live page opens with a floating translucent navigation bar, a coral-to-teal fashion palette, Fraunces editorial type, a large promise that weather, taste and wardrobe will agree, two cutout people, and animated catalog-image cards. Its story is aimed at someone with a full closet who still feels they have nothing to wear. The primary actions are Sign in, Create account and Enter the Atelier.

The rest of the live page has four short sections:

| Section | Message | Actual destination |
| --- | --- | --- |
| The Atelier | Outfit of the Day, Rate and complete, Wardrobe Completion | Descriptive cards only; sign in is the route into the app. |
| How it works | Add a garment photo, tell DressMe about the day, receive a look | Describes several separate app flows as one journey. |
| Now and next | Names current tools and an avatar/real try-on future | A broad status summary, now behind some integrated work. |
| Try-on mock | A private workflow preview | The link goes to `/login`, without preserving the try-on destination. |

The root page fetches up to 42 bundled catalog samples through `/api/public-style-wall` and `/public-wall/{key}.jpg` for the animated background. Those endpoints serve catalog images only, not private user uploads. The page also requests Google Fonts, so its typography depends on an external font service when online.

## Visual and interaction assessment

The opening is distinctive and easy to remember. The warm colors, fashion photography and moving cards support the theme. The hero has visible sign-in and account-creation actions, and the named sections give a first-time visitor a fast overview.

At the inspected 676 px viewport, the fixed header shows the logo and Sign in, while the section links disappear. The Atelier cards form two columns with one card alone on a second row. The fixed header remains visible during scrolling. The two Sign in buttons in the opening repeat the same action. The animation provides motion for the campaign; the page does disable CSS animation and the JavaScript image loop under `prefers-reduced-motion`.

The live page does not show Taste Studio, Style Profile, Bubble Breaker, Redundancy Check, the private wardrobe review flow, or the current Style Assistant chat status. Its headline makes Taste central, but the feature is absent from the detailed section. The mobile header has no replacement menu after its section links disappear. The animated image cards can compete with the headline and controls, especially in a narrower view.

## Content accuracy against the app

1. “Each one starts from what is already in your closet” is too broad. Some original outfit tools use the bundled catalog. Outfit of the Day has an explicit saved-catalog-wardrobe mode; other paths are not simply derived from the private BO6 wardrobe.
2. The live “Create account” URL is `/login?mode=signup`. The current login client reads `view=register`, so the link opens the sign-in view and the visitor must click Create an account again.
3. The try-on preview is not a generated fitting. On this checkout `VTON_MODE=mock`, and the try-on queue health reports `dispatcher_unavailable`; the landing page should not imply that a mock job can be completed here today.
4. The current app includes Taste and a redundancy workflow, while the live page does not introduce them. Style Assistant chat is intentionally paused on this PC because `DRESSME_PARSER_ENABLED=off`; its dressing and preference controls remain.
5. The “real virtual try-on on the way” wording should be updated carefully: a real FASHN adapter and optional remote path exist in code, but the current configuration is mock and no real result was verified during this inspection.

## The newer landing source

`landing/src/LandingPage.tsx` and `landing/src/style.css` describe a different, wardrobe-first editorial page: olive/sage/cream palette, still-life hero, a four-step photo → review → confirm → save illustration, a seven-card “now and next” moodboard, and a labelled try-on disclosure. It has a skip link, a mobile menu, responsive rules, reduced-motion handling and a direct `/login?next=%2Fapp%23bo6-add` wardrobe action. Its illustrations explicitly say that they are samples and do not display model predictions.

That source is **not the page currently served**. Vite is configured to build into `static/landing/`, and `scripts/dev/setup.ps1` runs that build. Running the setup/build will replace the older live page with the newer design. A normal app restart alone does not rebuild it. The generated `static/landing/` directory is ignored by Git.

The newer source also needs a content pass before it becomes the public story. It labels redundancy detection, personal style modelling and the fashion assistant as concepts even though related workflows are in the integrated app (the assistant chat is paused locally). It does not explain the Taste menu. Its “Read the live-fitting disclosure” link targets `#live-try-on`, but that ID does not exist in the component. It calls try-on a mock preview, which matches this checkout's configuration.

## Recommended next pass

1. Choose which design is the intended public landing; the live artifact and source currently disagree.
2. Align the chosen page's feature claims with catalog modes, Taste, the private wardrobe, the paused assistant and the actual try-on readiness state.
3. Fix the Create account URL (`?view=register`) and give the try-on link a destination after sign-in.
4. Restore section navigation on narrow screens and verify the hero, cards, focus order and motion at desktop and phone widths.
5. Rebuild the chosen source into `static/landing/` and verify the served page at `/` after the content decisions.

No landing source or build artifact was changed for this analysis.
