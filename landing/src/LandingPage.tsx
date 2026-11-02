import React, { useEffect, useRef, type MouseEvent } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

const landingSections = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#project-notes", label: "Now and next" },
  { href: "#try-on-notes", label: "Try-on mock" },
];

function closeMobileMenu(event: MouseEvent<HTMLAnchorElement>) {
  event.currentTarget.closest("details")?.removeAttribute("open");
}

function LandingLinks({ mobile = false }: { mobile?: boolean }) {
  return <nav aria-label={mobile ? "Mobile navigation" : "Main navigation"}>
    {landingSections.map((section) => <a key={section.href} href={section.href} onClick={mobile ? closeMobileMenu : undefined}>{section.label}</a>)}
  </nav>;
}

function GarmentShape({ kind, className }: { kind: "shirt" | "jacket" | "trousers"; className?: string }) {
  if (kind === "trousers") return <svg className={className} viewBox="0 0 260 370" aria-hidden="true" focusable="false">
    <path d="M38 28h184l-8 105-17 202H109l-7-153-14 153H37L49 133z" fill="#60413d" stroke="#392f2a" strokeWidth="5" strokeLinejoin="round" />
    <path d="M50 131h167M128 35v142" fill="none" stroke="#92756b" strokeWidth="3" />
    <circle cx="128" cy="65" r="4" fill="#c3a178" />
  </svg>;
  if (kind === "jacket") return <svg className={className} viewBox="0 0 360 430" aria-hidden="true" focusable="false">
    <path d="m104 44 75 28 76-28 65 48-38 112-38-20v206H111V184l-38 20-38-112z" fill="#596c55" stroke="#344538" strokeWidth="5" strokeLinejoin="round" />
    <path d="m105 47 54 24-24 76-42-48m164-52-54 24 23 76 43-48M180 73v318M155 76l25 38 25-38" fill="none" stroke="#9aa18a" strokeWidth="4" strokeLinejoin="round" />
    <path d="M130 230h43m34 0h43M130 280h43m34 0h43" stroke="#c5ad87" strokeWidth="4" />
  </svg>;
  return <svg className={className} viewBox="0 0 320 390" aria-hidden="true" focusable="false">
    <path d="m96 40 64 26 64-26 63 54-39 90-34-20v197H106V164l-34 20-39-90z" fill="#e4d7c0" stroke="#8e7c65" strokeWidth="5" strokeLinejoin="round" />
    <path d="M96 41c11 34 34 52 64 52s53-18 64-52M160 93v266" fill="none" stroke="#aa9881" strokeWidth="4" />
    <path d="M133 128v191m54-191v191" stroke="#c5b8a2" strokeWidth="3" />
  </svg>;
}

function ConceptMark({ kind }: { kind: string }) {
  if (kind === "scoring") return <span className="landing-concept-mark landing-mark-score" aria-hidden="true"><i /><b>✳</b></span>;
  if (kind === "daily") return <span className="landing-concept-mark landing-mark-daily" aria-hidden="true">↗<i>day / look</i></span>;
  if (kind === "completion") return <span className="landing-concept-mark landing-mark-completion" aria-hidden="true"><GarmentShape kind="shirt" /><i>?</i></span>;
  if (kind === "search") return <span className="landing-concept-mark landing-mark-search" aria-hidden="true"><i>⌕</i></span>;
  if (kind === "redundancy") return <span className="landing-concept-mark landing-mark-redundancy" aria-hidden="true"><i /><i /><i /></span>;
  if (kind === "style") return <span className="landing-concept-mark landing-mark-style" aria-hidden="true"><i /><i /><i /><i /></span>;
  return <span className="landing-concept-mark landing-mark-assistant" aria-hidden="true"><i>…</i></span>;
}

export default function LandingPage() {
  const pageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const page = pageRef.current;
    if (!page || typeof window.matchMedia !== "function") return;

    gsap.registerPlugin(ScrollTrigger);
    const motion = gsap.matchMedia();
    motion.add({
      motionOK: "(prefers-reduced-motion: no-preference)",
      desktop: "(min-width: 1000px)",
    }, ({ conditions }) => {
      if (!conditions?.motionOK) return;

      const context = gsap.context(() => {
        const hero = page.querySelector<HTMLElement>(".landing-hero");
        if (hero) {
          const campaign = gsap.timeline({
            scrollTrigger: { trigger: hero, start: "top 78%", once: true, invalidateOnRefresh: true },
            defaults: { ease: "power3.out" },
          });
          campaign.fromTo(".landing-hero-image-frame", { clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0% 0)", duration: 1.05 })
            .fromTo(".landing-hero-image", { scale: 1.19, yPercent: 7, rotate: -1.8 }, { scale: 1, yPercent: 0, rotate: 0, duration: 1.45 }, 0)
            .fromTo(".landing-hero-image-note", { x: 24, rotate: 7 }, { x: 0, rotate: 0, duration: .58 }, .48)
            .fromTo(".landing-hero-eyebrow", { x: -16 }, { x: 0, duration: .45 }, .22)
            .fromTo(".landing-title-line-inner", { yPercent: 112, rotateX: -7 }, { yPercent: 0, rotateX: 0, duration: .78, stagger: .14, ease: "power4.out" }, .32)
            .fromTo(".landing-hero-description", { y: 16 }, { y: 0, duration: .5 }, .76)
            .fromTo(".landing-hero-actions .landing-button", { scale: .97 }, { scale: 1, duration: .46 }, .88)
            .fromTo(".landing-hero-stamp", { x: 18, rotate: 4 }, { x: 0, rotate: -8, duration: .62 }, .62);
        }

        const flow = page.querySelector<HTMLElement>("#how-it-works");
        const flowSteps = page.querySelectorAll<HTMLElement>(".landing-flow-step");
        const progressFill = page.querySelector<HTMLElement>(".landing-flow-progress-fill");
        if (flow && flowSteps.length) {
          if (conditions.desktop) {
            const story = gsap.timeline({
              scrollTrigger: {
                trigger: flow,
                start: "top top",
                end: "+=1180",
                scrub: .75,
                pin: true,
                pinSpacing: true,
                anticipatePin: 1,
                invalidateOnRefresh: true,
              },
            });
            if (progressFill) story.to(progressFill, { scaleX: 1, duration: 3.8, ease: "none" }, 0);
            flowSteps.forEach((step, index) => {
              const at = index * .78;
              story.to(step, {
                y: -9,
                rotate: 0,
                scale: 1.025,
                borderColor: "#8d9b84",
                boxShadow: "0 18px 34px #26332121",
                duration: .3,
                ease: "power2.out",
              }, at).to(step, {
                y: 0,
                scale: 1,
                borderColor: "#d2d1c6",
                boxShadow: "0 8px 23px #26332112",
                duration: .36,
                ease: "power1.inOut",
              }, at + .38);
            });
          } else {
            const story = gsap.timeline({
              scrollTrigger: { trigger: flow, start: "top 72%", once: true, invalidateOnRefresh: true },
            });
            flowSteps.forEach((step, index) => {
              story.fromTo(step, { y: 16, rotate: index % 2 === 0 ? -1.2 : 1.2 }, { y: 0, rotate: 0, duration: .42 }, index * .12);
            });
            if (progressFill) story.fromTo(progressFill, { scaleY: 0 }, { scaleY: 1, duration: .8 }, .12);
          }
        }

        const moodboard = page.querySelector<HTMLElement>(".landing-moodboard");
        const concepts = page.querySelectorAll<HTMLElement>(".landing-concept");
        if (moodboard && concepts.length) {
          const collage = gsap.timeline({
            scrollTrigger: {
              trigger: moodboard,
              start: conditions.desktop ? "top 72%" : "top 84%",
              end: conditions.desktop ? "bottom 24%" : undefined,
              scrub: conditions.desktop ? .65 : false,
              once: !conditions.desktop,
              invalidateOnRefresh: true,
            },
          });
          concepts.forEach((concept, index) => {
            const initialRotation = index % 2 === 0 ? -5 : 5;
            collage.fromTo(concept, {
              y: 32 + (index % 3) * 7,
              x: index % 2 === 0 ? -12 : 12,
              rotate: initialRotation,
              scale: .94,
            }, {
              y: 0,
              x: 0,
              rotate: 0,
              scale: 1,
              duration: .72,
              ease: "power2.out",
            }, conditions.desktop ? index * .14 : index * .13);
          });
        }
      }, page);

      return () => context.revert();
    });

    return () => motion.revert();
  }, []);

  return <div className="landing-page" ref={pageRef}>
    <a className="landing-skip-link" href="#main-content">Skip to content</a>
    <header className="landing-header">
      <a className="landing-brand" href="#top" aria-label="DressMe home">
        <span className="landing-brand-mark" aria-hidden="true">D</span><span>dressme</span>
      </a>
      <div className="landing-desktop-links"><LandingLinks /></div>
      <details className="landing-mobile-menu">
        <summary aria-label="Open navigation menu"><span aria-hidden="true">☰</span> Menu</summary>
        <LandingLinks mobile />
      </details>
      <div className="landing-header-actions">
        <a className="landing-signin" href="/login">Sign in</a>
        <a className="landing-button landing-button-dark" href="/login?next=%2Fapp%23bo6-add">Start with your wardrobe</a>
      </div>
    </header>

    <main id="main-content" tabIndex={-1}>
      <section id="top" className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <p className="landing-eyebrow landing-hero-eyebrow"><span aria-hidden="true" /> A wardrobe, seen a little differently</p>
          <h1 id="landing-title" aria-label="More possibility from the pieces you own.">
            <span className="landing-title-line"><span className="landing-title-line-inner">More possibility</span></span>
            <span className="landing-title-line landing-title-line-italic"><span className="landing-title-line-inner">from the pieces you own.</span></span>
          </h1>
          <p className="landing-hero-description">DressMe starts with a useful record of your clothes. Add a garment photo, review the details suggested for it and build a wardrobe you can search, filter and make your own.</p>
          <div className="landing-hero-actions">
            <a className="landing-button landing-button-dark" href="/login?next=%2Fapp%23bo6-add">Organize your wardrobe <span aria-hidden="true">↗</span></a>
            <a className="landing-text-link" href="#how-it-works">See how it works <span aria-hidden="true">↓</span></a>
          </div>
          <p className="landing-hero-footnote">One garment at a time. Your choices stay yours.</p>
        </div>
        <figure className="landing-hero-art">
          <div className="landing-hero-image-frame">
            <img className="landing-hero-image" src="/landing/dressme-editorial-still-life.webp" alt="An editorial still-life of an olive jacket, soft knit and plum trousers on a wooden rail." width="1122" height="1402" fetchPriority="high" />
            <span className="landing-hero-image-note" aria-hidden="true">Pieces in<br />their own light</span>
          </div>
          <span className="landing-hero-stamp">A wardrobe<br />in progress <span aria-hidden="true">✳</span></span>
          <figcaption><span>DressMe / 01</span><span>Clothes, kept in your own orbit.</span></figcaption>
        </figure>
        <div className="landing-hero-index" aria-hidden="true">WARDROBE STUDIES<br />NO. 001 / 007</div>
      </section>

      <section id="how-it-works" className="landing-flow-story landing-section" aria-labelledby="flow-title">
        <span id="outfit-story" className="landing-anchor-alias" aria-hidden="true" />
        <div className="landing-flow-shell">
          <div className="landing-flow-heading">
            <div>
              <p className="landing-eyebrow"><span aria-hidden="true" /> In the app today · BO6</p>
              <h2 id="flow-title">From a photo to <em>your own record.</em></h2>
            </div>
            <div className="landing-flow-intro">
              <p>Add one garment at a time. Review suggestions, confirm the details that belong, and save an item you can manage yourself.</p>
              <span className="landing-status">Working wardrobe flow</span>
            </div>
          </div>

          <div className="landing-flow-board" aria-label="Illustration of the implemented wardrobe flow. The garment photo is generated for this page; no model suggestion values are shown.">
            <p className="landing-flow-board-note">Illustrative flow · sample garment image · no model values shown</p>
            <div className="landing-flow-track">
              <div className="landing-flow-progress" aria-hidden="true"><span className="landing-flow-progress-fill" /></div>
              <ol className="landing-flow-steps">
                <li className="landing-flow-step landing-flow-step-photo">
                  <span className="landing-flow-number">01 <i>PHOTO</i></span>
                  <figure className="landing-flow-photo">
                    <img src="/landing/dressme-search-sample.webp" alt="Generated illustrative photo of a blue shirt, used to represent a garment photo." width="1254" height="1254" loading="lazy" />
                    <figcaption>Illustrative image</figcaption>
                  </figure>
                  <h3>Choose a photo</h3>
                  <p>Start with one clear JPEG, PNG or WEBP garment image.</p>
                </li>
                <li className="landing-flow-step landing-flow-step-review">
                  <span className="landing-flow-number">02 <i>REVIEW</i></span>
                  <div className="landing-flow-illustration landing-suggestion-illustration" aria-hidden="true">
                    <span className="landing-flow-ui-title">Suggestions <small>For your review</small></span>
                    <span className="landing-flow-ui-row"><i>Category</i><b>Choose a suggestion</b></span>
                    <span className="landing-flow-ui-row"><i>Attributes</i><b>Not confirmed</b></span>
                    <span className="landing-flow-ui-foot">Nothing is confirmed until you choose it.</span>
                  </div>
                  <h3>Review suggestions</h3>
                  <p>Suggested category and attributes stay unconfirmed until you select them.</p>
                </li>
                <li className="landing-flow-step landing-flow-step-confirm">
                  <span className="landing-flow-number">03 <i>CONFIRM</i></span>
                  <div className="landing-flow-illustration landing-confirm-illustration" aria-hidden="true">
                    <span className="landing-flow-ui-title">Before saving</span>
                    <span className="landing-confirm-row"><i>Category</i><b>Confirm</b></span>
                    <span className="landing-confirm-row"><i>Photo type</i><b>Select</b></span>
                    <span className="landing-confirm-row landing-confirm-optional"><i>Description</i><b>Edit if you like</b></span>
                  </div>
                  <h3>You decide what fits</h3>
                  <p>Confirm the required category and photo type; edit the description if you want.</p>
                </li>
                <li className="landing-flow-step landing-flow-step-saved">
                  <span className="landing-flow-number">04 <i>SAVE</i></span>
                  <div className="landing-flow-illustration landing-saved-illustration" aria-hidden="true">
                    <img className="landing-flow-saved-art" src="/landing/dressme-editorial.svg" alt="" loading="lazy" />
                    <span className="landing-flow-saved-check">✓</span>
                    <span className="landing-flow-ui-title">Saved by you <small>Wardrobe item</small></span>
                    <span className="landing-flow-saved-rule" />
                    <span className="landing-flow-saved-meta">Search · filter · edit · export</span>
                  </div>
                  <h3>Keep your record</h3>
                  <p>Save the garment, then search, filter, edit or export your wardrobe.</p>
                </li>
              </ol>
            </div>
          </div>
        </div>
      </section>

      <section id="project-notes" className="landing-future-story landing-section" aria-labelledby="future-title">
        <div className="landing-future-heading">
          <div>
            <p className="landing-eyebrow"><span aria-hidden="true" /> The wider DressMe project</p>
            <h2 id="future-title">DressMe, <em>now and next.</em></h2>
          </div>
          <div className="landing-future-intro">
            <p>Explore the tools in the integrated app and the ideas still in study.</p>
            <span className="landing-status landing-status-future">Four live tools · three concepts</span>
          </div>
        </div>

        <div className="landing-moodboard" aria-label="Editorial moodboard of DressMe tools and future concepts">
          <article className="landing-concept landing-concept-scoring">
            <ConceptMark kind="scoring" />
            <span className="landing-concept-kicker">01 / WHAT IF</span>
            <h3>Outfit scoring</h3>
            <p>Score a look and explore replacement suggestions.</p>
            <span className="landing-concept-status">In the app · The Verdict</span>
          </article>
          <article className="landing-concept landing-concept-daily">
            <ConceptMark kind="daily" />
            <span className="landing-concept-kicker">02 / A NEW DAY</span>
            <h3>Daily outfit recommendations</h3>
            <p>See an outfit suggestion for today’s weather.</p>
            <span className="landing-concept-status">In the app · Daily Edit</span>
          </article>
          <article className="landing-concept landing-concept-completion">
            <ConceptMark kind="completion" />
            <span className="landing-concept-kicker">03 / THE NEXT PIECE</span>
            <h3>Wardrobe completion</h3>
            <p>Explore pieces that may round out a collection.</p>
            <span className="landing-concept-status">In the app · Shopping</span>
          </article>
          <article id="visual-search" className="landing-concept landing-concept-search">
            <img className="landing-concept-search-image" src="/landing/dressme-search-sample.webp" alt="Generated garment image illustrating the photo input for Find Similar." width="1254" height="1254" loading="lazy" />
            <span className="landing-concept-search-lens" aria-hidden="true">⌕</span>
            <span className="landing-concept-kicker">04 / FOLLOW THE THREAD</span>
            <h3>Visual fashion search</h3>
            <p>Upload an image to find similar pieces.</p>
            <span className="landing-concept-status">In the app · Find Similar</span>
          </article>
          <article className="landing-concept landing-concept-redundancy">
            <ConceptMark kind="redundancy" />
            <span className="landing-concept-kicker">05 / NOTICE</span>
            <h3>Redundancy detection</h3>
            <p>See how pieces might share a role.</p>
            <span className="landing-concept-status">Project direction · not in the app yet</span>
          </article>
          <article className="landing-concept landing-concept-style">
            <ConceptMark kind="style" />
            <span className="landing-concept-kicker">06 / PERSONAL THREAD</span>
            <h3>Personal style modeling</h3>
            <p>Learn from the preferences you choose to share.</p>
            <span className="landing-concept-status">Concept</span>
          </article>
          <article className="landing-concept landing-concept-assistant">
            <ConceptMark kind="assistant" />
            <span className="landing-concept-kicker">07 / A CONVERSATION</span>
            <h3>Fashion assistant</h3>
            <p>A place to ask better questions about what you own.</p>
            <span className="landing-concept-status">Concept</span>
          </article>
          <span className="landing-moodboard-caption">DressMe / now and next · 01—07</span>
        </div>

        <aside id="try-on-notes" className="landing-tryon-disclosure" aria-labelledby="tryon-title">
          <div>
            <p className="landing-eyebrow"><span aria-hidden="true" /> Research &amp; prototype · BO7</p>
            <h3 id="tryon-title">Virtual try-on is still a mock preview.</h3>
            <p>The in-app Try-on Preview is a labelled mock workflow. It does not generate a try-on image or predict fit. Avatar workflows are partial and have not been verified end to end.</p>
          </div>
          <div className="landing-tryon-links">
            <a className="landing-button landing-button-outline" href="/login?next=%2Fapp%23bo7-tryon">Open the mock preview <span aria-hidden="true">↗</span></a>
            <a className="landing-text-link" href="#live-try-on">Read the live-fitting disclosure <span aria-hidden="true">↗</span></a>
          </div>
          <p className="landing-tryon-note">Live fitting uses a separate third-party service, with disclosure and consent before it loads.</p>
        </aside>
      </section>

      <section className="landing-closing landing-section" aria-labelledby="closing-title">
        <p className="landing-eyebrow"><span aria-hidden="true" /> A good place to begin</p>
        <h2 id="closing-title">Start with the piece you reach for.</h2>
        <p>Add a garment, review the details and build your wardrobe from there.</p>
        <a className="landing-button landing-button-dark" href="/login?next=%2Fapp%23bo6-add">Build your wardrobe <span aria-hidden="true">↗</span></a>
      </section>
    </main>

    <footer className="landing-footer" id="about">
      <a className="landing-brand landing-footer-brand" href="#top"><span className="landing-brand-mark" aria-hidden="true">D</span><span>dressme</span></a>
      <p>Fashion, with a little more context.</p>
      <a href="/login">Sign in to DressMe <span aria-hidden="true">↗</span></a>
    </footer>
  </div>;
}


