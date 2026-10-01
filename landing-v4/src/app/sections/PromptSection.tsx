'use client';

import { useEffect, useRef } from 'react';

export function PromptSection() {
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const text = document.getElementById('promptText');
    const input = document.getElementById(
      'promptInput'
    ) as HTMLTextAreaElement | null;
    const tags = Array.from(
      document.querySelectorAll<HTMLButtonElement>('#ptags .ptag')
    );
    const clear = document.getElementById('promptClear');
    const go = document.getElementById('promptGo');
    const reduce = window.matchMedia(
      '(prefers-reduced-motion: reduce)'
    ).matches;

    const examples = [
      {
        cat: 'local',
        p: 'People who visit [your competitors] in [your city] at least twice a month',
        f: 'Finding devices seen at competing businesses across your city',
        n: '3,872',
      },
      {
        cat: 'ecom',
        p: 'I run an online sneaker marketplace. Reach people who went to both Sneakersnstuff and Foot Locker in the last 30 days',
        f: 'Finding devices seen at sneaker stores in the last 30 days',
        n: '27,318',
      },
      {
        cat: 'rest',
        p: 'Diners who eat at ramen places in Brooklyn on weeknights',
        f: 'Finding devices seen at ramen restaurants across Brooklyn on weeknights',
        n: '15,204',
      },
      {
        cat: 'fit',
        p: 'People who go to CrossFit gyms in Austin at least twice a week',
        f: 'Finding devices seen at CrossFit gyms across Austin',
        n: '8,631',
      },
      {
        cat: 'saas',
        p: 'Staff at the 50 biggest tech offices in downtown Seattle',
        f: 'Finding devices seen at tech office buildings in downtown Seattle',
        n: '46,915',
      },
      {
        cat: 'estate',
        p: 'Renters who toured apartment buildings in Austin in the last 60 days',
        f: 'Finding devices seen at apartment leasing offices across Austin',
        n: '6,247',
      },
      {
        cat: 'b2b',
        p: 'Buyers who walked the trade show floor at the Javits Center this spring',
        f: 'Finding devices seen on the trade show floor this spring',
        n: '19,782',
      },
      {
        cat: 'vibecoders',
        p: "I built a pickleball court booking app over a weekend. I want to get my first users. Only target people who've played at a pickleball court in Austin in the last 30 days.",
        f: 'Finding devices seen at pickleball courts across Austin in the last 30 days',
        n: '14,820',
      },
      {
        cat: 'wtf',
        p: 'People who went to the same dog park as my ex. Do not ask.',
        f: 'Finding devices seen at one very specific dog park',
        n: '317',
      },
    ];

    const sayEl = document.getElementById('psay');
    const sayText = document.getElementById('psayText');
    const keyMk = document.getElementById('promptMk');

    let i = 0;
    let own = false;
    let run = 0;
    let dotTimer: ReturnType<typeof setInterval> | number = 0;

    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const light = (cat: string | null) =>
      tags.forEach((t) => t.classList.toggle('is-on', t.dataset.cat === cat));

    function say(html: string, dots: boolean) {
      clearInterval(dotTimer);
      dotTimer = 0;
      if (sayText) {
        sayText.innerHTML =
          html + (dots ? '<i class="psay__dots" aria-hidden="true"></i>' : '');
      }
      sayEl?.classList.add('is-on');
      if (dots && sayText) {
        const d = sayText.querySelector('.psay__dots');
        let k = 0;
        dotTimer = setInterval(() => {
          k = (k + 1) % 4;
          if (d) d.textContent = '.'.repeat(k);
        }, 360);
      }
    }

    function hush() {
      clearInterval(dotTimer);
      dotTimer = 0;
      sayEl?.classList.remove('is-on');
      if (sayText) sayText.textContent = '';
      if (keyMk) keyMk.classList.remove('is-jump');
    }

    async function cycle(token: number, start?: number) {
      if (reduce) {
        const ex = examples[start || 0];
        if (text) text.textContent = ex.p;
        light(ex.cat);
        return;
      }
      i = start === undefined ? i : start;
      while (true) {
        if (token !== run) return;
        const ex = examples[i % examples.length];
        i++;
        hush();
        if (text) text.textContent = '';
        light(ex.cat);

        if (text) {
          for (const ch of ex.p) {
            if (token !== run) return;
            text.textContent += ch;
            await wait(24 + Math.random() * 26);
          }
        }
        await wait(420);
        if (token !== run) return;
        say(ex.f, true);
        await wait(2500);
        if (token !== run) return;
        say('Found <b class="psay__n">' + ex.n + '</b> devices', false);
        if (keyMk && !reduce) {
          keyMk.classList.remove('is-jump');
          void keyMk.offsetWidth;
          keyMk.classList.add('is-jump');
        }
        await wait(2900);
        if (token !== run) return;
        hush();
        if (text) {
          while (text.textContent && text.textContent.length) {
            if (token !== run) return;
            text.textContent = text.textContent.slice(0, -2);
            await wait(10);
          }
        }
        await wait(300);
      }
    }

    function takeOver(seed?: string) {
      own = true;
      run++;
      section?.classList.add('is-typing');
      hush();
      if (seed !== undefined && input) input.value = seed;
      if (input) {
        input.focus();
        if (seed === undefined) {
          const l = input.value.length;
          input.setSelectionRange(l, l);
        }
      }
    }

    const area = section.querySelector('.prompt__area');
    const handleAreaClick = () => {
      if (!own) takeOver('');
    };
    area?.addEventListener('click', handleAreaClick);

    const handleInput = () => {
      if (!input) return;
      const v = input.value.toLowerCase();
      let best: string | null = null;
      let score = 0;
      for (const ex of examples) {
        const words = ex.p
          .toLowerCase()
          .split(/[^a-z]+/)
          .filter((w) => w.length > 4);
        const n = words.filter((w) => v.includes(w)).length;
        if (n > score) {
          score = n;
          best = ex.cat;
        }
      }
      light(score ? best : null);
    };
    input?.addEventListener('input', handleInput);

    const handleClear = () => {
      own = false;
      if (input) input.value = '';
      section?.classList.remove('is-typing');
      run++;
      cycle(run);
    };
    clear?.addEventListener('click', handleClear);

    const tagListeners: Array<() => void> = [];
    tags.forEach((t) => {
      const handler = () => {
        const idx = examples.findIndex((e) => e.cat === t.dataset.cat);
        if (idx === -1) return;

        // Give control back to the animation instead of the user
        own = false;
        if (input) input.value = '';
        section?.classList.remove('is-typing');

        run++; // cancel the currently running cycle
        cycle(run, idx); // restart the loop from the clicked example
      };
      tagListeners.push(handler);
      t.addEventListener('click', handler);
    });

    const handleGo = () => {
      const v = (own && input ? input.value : text?.textContent || '').trim();
      try {
        sessionStorage.setItem('punk:prompt', v);
      } catch {}
    };
    go?.addEventListener('click', handleGo as EventListener);

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-in');
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    io.observe(section);

    cycle(++run);

    return () => {
      run++;
      io.disconnect();
      clearInterval(dotTimer);
      area?.removeEventListener('click', handleAreaClick);
      input?.removeEventListener('input', handleInput);
      clear?.removeEventListener('click', handleClear);
      tags.forEach((t, idx) =>
        t.removeEventListener('click', tagListeners[idx])
      );
      go?.removeEventListener('click', handleGo as EventListener);
    };
  }, []);

  return (
    <section
      className="prompt reveal"
      aria-label="Describe who you want to reach"
      ref={sectionRef}
    >
      <div className="wrap">
        <div className="prompt__card">
          <label className="prompt__area" htmlFor="promptInput">
            <span className="prompt__label">
              Describe who you want to reach
            </span>
            <span className="prompt__line" data-ride-whole>
              <span
                id="promptText"
                className="prompt__text"
                aria-hidden="true"
              ></span>
              <span className="prompt__caret" aria-hidden="true"></span>
            </span>
            <textarea
              id="promptInput"
              className="prompt__input"
              rows={2}
              spellCheck={false}
              placeholder="Describe who you want to reach…"
              aria-label="Describe who you want to reach"
            />
          </label>
          <div className="prompt__bar">
            <button
              id="promptClear"
              className="prompt__clear"
              type="button"
              aria-label="Start a new prompt"
            >
              <i
                id="promptMk"
                className="mk mk--main"
                aria-hidden="true"
                style={{
                  backgroundImage: `url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0OSIgaGVpZ2h0PSI1MiIgdmlld0JveD0iMCAwIDQ4LjU0IDUxLjA5IiBmaWxsPSJub25lIj48Zz4KPHBhdGggZD0iTTQ1LjMyMzUgNTEuMDg0SDQwLjE2MTZWNDYuMTA4NUgzNS45MDIyVjQ3Ljk2MDFIMzcuNjAxNlY1MS4wODM0SDM2LjA1NzhWNTEuMDg0SDMwLjQzMDJWNDcuOTYwMUgyNi45NDk1VjQ3Ljk2NzlIMjcuOTgyMVY1MS4wODRIMjMuNDY4M1Y0NC43MDE1SDIwLjMzMDFWNTEuMDg0SDEzLjY0NDlWNDQuOTI2NUgwVjMyLjI5ODRINi4yNzY4OFYzNS40ODkxSDIuOTEwMzlWNDIuMDA1MkgxMy43ODEyVjM5LjAzOUgxNy4zMjg5VjMyLjM0MjhMMjIuMDc0NCAzMC43MTkxTDE4Ljk2NTIgMjAuMjk5TDIyLjg3NyAxOS4yMTk3VjE3Ljk2MTlMMjguNjk4NCAxNi4zNDM5TDI5LjE1MzMgMTcuMTA3N0wzNy4yMjQ1IDE0LjkyMTFMMzcuODM1MSAxNi4xMTMyTDQ1LjI0NDUgMTMuODg2N0w0Ni4wNDIgMTYuODQyMkw0Mi4wNDk2IDE5LjMxMDFWMzUuNTc4OUg0NS4zMjM1VjUxLjA4NFoiIGZpbGw9IiM3MzMwMTYiLz4KPHBhdGggZD0iTTM3LjQzMzggMzIuMzQ0N0gzMy45NTMxVjM1LjQ2ODFIMzcuNDMzOFYzMi4zNDQ3WiIgZmlsbD0iIzczMzAxNiIvPgo8cGF0aCBkPSJNMzMuOTc0OCAzMi4zNDQ3SDMwLjQ5NDFWMzUuNDY4MUgzMy45NzQ4VjMyLjM0NDdaIiBmaWxsPSIjNzMzMDE2Ii8+CjxwYXRoIGQ9Ik00Ni4wNDM1IDE2Ljg0MjJMNDAuOTE1MSAxOS4zMTAxTDMyLjU2MTcgMzIuODM4NEwyMy43MjU0IDM1LjUxMDVMMTguOTY2OCAyMC4yOTk1TDIyLjg3ODYgMTkuMjIwM1YxNy45NjI1TDI4LjY5OTkgMTYuMzQ0NEwyOS4xNTQ5IDE3LjEwNzdMMzcuMjI2IDE0LjkyMTdMMzcuODM2NiAxNi4xMTM3TDQ1LjI0NjEgMTMuODg2N0w0Ni4wNDM1IDE2Ljg0MjJaIiBmaWxsPSIjODQzODE4Ii8+CjxwYXRoIGQ9Ik00OC41Mzc2IDI1Ljk1M0w0Ni4wNDMgMTYuODQxN0w0My43MjY3IDE3LjQxNDJMNDMuMjgwOCAxNS43NDE3TDM5LjU4MzggMTYuODQxN0wzOS4yNDg2IDE2LjA1NjZMMjkuNjQzMyAxOC41M0wzMC4xNjgyIDIwLjIxMTVMMjYuMTkzNCAyMS4yNzk1TDI4Ljc1NzMgMzAuMDU5MUwzMS40NzUxIDI5LjE2NzlMMzIuNTYxMSAzMi44Mzc5TDQ2LjI5OTEgMjkuMDQzOEw0NS42NTc5IDI2LjY5NzhMNDguNTM3NiAyNS45NTNaIiBmaWxsPSIjRUU5QjU5Ii8+CjxwYXRoIGQ9Ik0xMy42NDQ5IDUxLjA4MzRIMjAuMzMwMUwyMC4yMjczIDQ0LjgzNjdIMjguMDk0NlYyOC44MTk4TDE3LjMyODkgMzIuMzQyOFYzOS4wMzlIMTMuNzgxMlY0Mi4wMDQ2SDIuOTEwMzlWMzUuNDg4Nkg2LjI3Njg4VjMyLjI5NzlIMFY0NC45MjU5SDEzLjY0NDlWNTEuMDgzNFoiIGZpbGw9IiM4NDM4MTgiLz4KPHBhdGggZD0iTTI0LjA3NzUgMjQuNTc3NkwxNy4xMjMgMjYuNjE2MUwxOS4yNzc0IDMyLjgzODFMMjYuMDMzNyAzMC44NjE0TDI0LjA3NzUgMjQuNTc3NloiIGZpbGw9IiNFRTlCNTkiLz4KPHBhdGggZD0iTTIwLjIyNjYgNDQuODM2OEgyOC4wOTM4VjM5LjEyMTZIMjMuOTE1N1Y0Mi4wNTkySDIwLjIyNjZWNDQuODM2OFoiIGZpbGw9IiNFRDlBNTYiLz4KPHBhdGggZD0iTTQzLjQxNTIgMTYuMjI4NUw0MC41MzMyIDUuMzE3ODJMMzkuNDU2OCA4LjkyMDQ3TDM2LjA1NCAwSDM0Ljk0M0wzNS40NjM5IDIuNTczMzJMMzQuMzUyOSAyLjcxMDI2TDM1LjQ2MzkgNy42NTA5M0wzMi40NDMzIDQuMjU0MjZMMzAuOTg0NyA0LjQ5NDQ3TDMyLjgyNSAxMC40OTg3TDI4LjQxNTEgNi45MzA4NEwyNy4wOTU2IDcuNDEwNzFMMjguNjIzNSAxMi4wMDg1TDI0LjUyNjYgOS45ODQwM0wyMi45OTg3IDEwLjE5TDI2LjUwNTUgMTQuNTgxOEwyMS40MDk1IDEzLjc1ODRMMjAuMDQ3NCAxNC4yMDQxTDIzLjMxMTEgMTcuNDI5NUwxOS40NTY3IDE3LjI1NzhMMTguNTE5NSAxNy43NzI1TDIyLjg0ODggMTkuNDIwOEwyMi44NzIxIDE4LjI4NzFMMjguMjc2NSAxNi41NzE0TDI4LjkzNTkgMTcuNjAwN0wzNi4yMjc4IDE1LjY0NTNMMzYuNzQ4NyAxNi43MDg5TDM5LjI0ODQgMTYuMDU2N0wzOS42OTk5IDE3LjI5Mkw0My40MTUyIDE2LjIyODVaIiBmaWxsPSIjQ0UxQzY2Ii8+CjxwYXRoIGQ9Ik00My40MTU1IDE2LjIyODVMNDAuNTMzNSA1LjMxNzgyTDQwLjAwMTkgMTAuMzcyNEwzNi4wNTQ0IDBIMzQuOTQzNEwzNy41MDA1IDkuNTQ1N0wzNS44NjggOS41NjU5TDM3LjExNzYgMTMuMjQ5NEwzOS4xNjMgMTIuOTUwOEwzOS40OTUyIDE0LjY0MjlINDEuMTI3N0w0MS43NTkzIDE2LjcwMjdMNDMuNDE1NSAxNi4yMjg1WiIgZmlsbD0iI0Y1NDM5NyIvPgo8cGF0aCBkPSJNMzQuMzg4MyA2LjQ0MjYzVjkuNTMxNzNIMzMuOTM0TDMwLjk4NDQgNC40OTUxTDMyLjQ0MyA0LjI1NDg4TDM0LjM4ODMgNi40NDI2M1oiIGZpbGw9IiNGNTQzOTciLz4KPHBhdGggZD0iTTMwLjY2OTUgOC43NTU3VjExLjc3NjNMMjcuMDk1NyA3LjQxMTUxTDI4LjQxNTEgNi45MzE2NEwzMC42Njk1IDguNzU1N1oiIGZpbGw9IiNGNTQzOTciLz4KPHBhdGggZD0iTTI3LjIzMyAxMS4zMjUzTDI4LjA5NDYgMTMuMzU1M0wyNC4yOTE5IDExLjgxMDJMMjIuOTk4IDEwLjE4OTlMMjQuNTI1OSA5Ljk4Mzg5TDI3LjIzMyAxMS4zMjUzWiIgZmlsbD0iI0Y1NDM5NyIvPgo8cGF0aCBkPSJNMjMuMTQ0NCAxNC4wMzg0TDIzLjk1NjYgMTYuMDMyNUwyMC4wNDg4IDE0LjIwMzlMMjEuNDEwOSAxMy43NTgzTDIzLjE0NDQgMTQuMDM4NFoiIGZpbGw9IiNGNTQzOTciLz4KPHBhdGggZD0iTTI4LjI3NjIgMTYuNTcxTDI3LjY2OSAxNS41NTU3TDI1LjY5OTIgMTUuODg5TDI2LjQ3NTEgMTcuMTI4M0wyOC4yNzYyIDE2LjU3MVoiIGZpbGw9IiNGNTQzOTciLz4KPHBhdGggZD0iTTI5LjM3MTEgMTMuNjg4NUwzMC40NjY4IDE1LjQ3MjFMMzIuMzcwNyAxNS4xNTIyTDMxLjA1MTggMTMuNDE4TDI5LjM3MTEgMTMuNjg4NVoiIGZpbGw9IiNGNTQzOTciLz4KPHBhdGggZD0iTTMxLjIwMzEgMTIuMTUwOUwzMy40MTg5IDE0LjY0NzlMMzUuODE5MiAxMy42NzQxTDM1LjY0MjUgMTIuNjgyNEwzNS4yNTY5IDEyLjg0MjRMMzMuNjg3IDExLjM4ODJMMzEuMjAzMSAxMi4xNTA5WiIgZmlsbD0iI0Y1NDM5NyIvPgo8cGF0aCBkPSJNMzcuNjAwNCA0Ny45NjA0SDM2LjA1NjZWNTEuMDgzOEgzNy42MDA0VjQ3Ljk2MDRaIiBmaWxsPSIjMzEzMTMxIi8+CjxwYXRoIGQ9Ik0zNy42MDI1IDQ3Ljk2MDRIMzMuOTUzMVY1MS4wODM4SDM3LjYwMjVWNDcuOTYwNFoiIGZpbGw9IiM4NDM4MTgiLz4KPHBhdGggZD0iTTQ2LjcxMTIgNDcuOTYwNEg0Mi42MDc0VjUxLjA4MzhINDYuNzExMlY0Ny45NjA0WiIgZmlsbD0iIzczMzAxNiIvPgo8cGF0aCBkPSJNMjcuOTgzOCA0Ny45Njc4SDI2Ljk1MTJWNTEuMDkwNkgyNy45ODM4VjQ3Ljk2NzhaIiBmaWxsPSIjMzEzMTMxIi8+CjxwYXRoIGQ9Ik0zMy45MzM4IDQ3Ljk2MDRIMzAuNDUzMVY1MS4wODM4SDMzLjkzMzhWNDcuOTYwNFoiIGZpbGw9IiM4NDM4MTgiLz4KPHBhdGggZD0iTTI3Ljk4NCA0Ny45Njc4SDIzLjQ3MDdWNTEuMDkwNkgyNy45ODRWNDcuOTY3OFoiIGZpbGw9IiM3MzMwMTYiLz4KPHBhdGggZD0iTTIxLjQ1ODYgNDcuOTY3OEgxNi45NDUzVjUxLjA5MTFIMjEuNDU4NlY0Ny45Njc4WiIgZmlsbD0iIzg0MzgxOCIvPgo8cGF0aCBkPSJNMjYuOTUxNCA0NC44MzY5SDIzLjQ3MDdWNDcuOTYwM0gyNi45NTE0VjQ0LjgzNjlaIiBmaWxsPSIjNzMzMDE2Ii8+CjxwYXRoIGQ9Ik0zMC40NjExIDQ0LjgzNjlIMjYuOTgwNVY0Ny45NTk3SDMwLjQ2MTFWNDQuODM2OVoiIGZpbGw9IiM3MzMwMTYiLz4KPHBhdGggZD0iTTM3LjQzMzggNDEuNzE0OEgzMy45NTMxVjQ0LjgzODJIMzcuNDMzOFY0MS43MTQ4WiIgZmlsbD0iIzg0MzgxOCIvPgo8cGF0aCBkPSJNMzcuNDMzOCAzOC41OTE4SDMzLjk1MzFWNDEuNzE1MUgzNy40MzM4VjM4LjU5MThaIiBmaWxsPSIjRjQ5NjRFIi8+CjxwYXRoIGQ9Ik0zNy40MzM4IDM1LjQ2ODNIMzMuOTUzMVYzOC41OTE2SDM3LjQzMzhWMzUuNDY4M1oiIGZpbGw9IiNGNDk2NEUiLz4KPHBhdGggZD0iTTMzLjgwMTcgMjIuNzk0NEwzMC40ODQ0IDIzLjgzNTRMMzEuNDQxMiAyNi44MTIzTDM0Ljc1ODUgMjUuNzcxMkwzMy44MDE3IDIyLjc5NDRaIiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNNDYuNjEwNyAxOS43MTgxTDQzLjI0OCAyMC42MDZMNDQuMDY0IDIzLjYyMzRMNDcuNDI2NyAyMi43MzU2TDQ2LjYxMDcgMTkuNzE4MVoiIGZpbGw9ImJsYWNrIi8+CjxwYXRoIGQ9Ik0zMy45NzQ4IDM1LjQ2ODNIMzAuNDk0MVYzOC41OTE2SDMzLjk3NDhWMzUuNDY4M1oiIGZpbGw9IiM3MzMwMTYiLz4KPHBhdGggZD0iTTQwLjkxMjMgMzIuMzQ0N0gzNy40MzE2VjM1LjQ2ODFINDAuOTEyM1YzMi4zNDQ3WiIgZmlsbD0iIzczMzAxNiIvPgo8cGF0aCBkPSJNNDAuOTEyMyAzNS40NjgzSDM3LjQzMTZWMzguNTkxNkg0MC45MTIzVjM1LjQ2ODNaIiBmaWxsPSIjNzMzMDE2Ii8+CjxwYXRoIGQ9Ik00MC45MTIzIDM4LjU5MTNIMzcuNDMxNlY0MS43MTQ2SDQwLjkxMjNWMzguNTkxM1oiIGZpbGw9IiM3MzMwMTYiLz4KPHBhdGggZD0iTTQwLjA2MDcgNDAuODczSDM2LjU4MDFWNDMuOTk2NEg0MC4wNjA3VjQwLjg3M1oiIGZpbGw9IiNGNDk2NEUiLz4KPHBhdGggZD0iTTMzLjk3NDggMzguNTkxM0gzMC40OTQxVjQxLjcxNDZIMzMuOTc0OFYzOC41OTEzWiIgZmlsbD0iIzg0MzgxOCIvPgo8cGF0aCBkPSJNMzMuOTc0OCA0MS43MTQ4SDMwLjQ5NDFWNDQuODM4MkgzMy45NzQ4VjQxLjcxNDhaIiBmaWxsPSIjODQzODE4Ii8+CjxwYXRoIGQ9Ik0zMC40NjIzIDM1LjQ2ODNIMjguMDkzOFYzOC41OTE2SDMwLjQ2MjNWMzUuNDY4M1oiIGZpbGw9IiM4NDM4MTgiLz4KPHBhdGggZD0iTTMwLjQ2MjMgMzguNTkxM0gyOC4wOTM4VjQxLjcxNDZIMzAuNDYyM1YzOC41OTEzWiIgZmlsbD0iIzg0MzgxOCIvPgo8cGF0aCBkPSJNMzAuNDYyMyA0MS43MTQ4SDI4LjA5MzhWNDQuODM4MkgzMC40NjIzVjQxLjcxNDhaIiBmaWxsPSIjODQzODE4Ii8+CjxwYXRoIGQ9Ik0zNS45MDA5IDQ0LjgzNjlIMzAuNDk0MVY0Ny45NTk3SDM1LjkwMDlWNDQuODM2OVoiIGZpbGw9IiM4NDM4MTgiLz4KPC9nPgo8L3N2Zz4=")`,
                }}
              />
            </button>
            <span id="psay" className="psay" aria-live="polite">
              <span id="psayText"></span>
            </span>
            <a
              className="prompt__go"
              href="https://chat.usepunk.ai/login"
              target="_blank"
              rel="noopener noreferrer"
              id="promptGo"
              aria-label="Target this audience"
              title="Target this audience"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </a>
          </div>
        </div>
        {/* <div className="ptags" id="ptags">
          <button className="ptag" type="button" data-cat="local">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12Z" />
              <circle cx="12" cy="10" r="2.5" />
            </svg>
            Local service
          </button>
          <button className="ptag" type="button" data-cat="ecom">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="9" cy="20" r="1.4" />
              <circle cx="18" cy="20" r="1.4" />
              <path d="M2 3h3l2.4 12.3a2 2 0 0 0 2 1.7h7.7a2 2 0 0 0 2-1.6L21 7H6" />
            </svg>
            Ecommerce
          </button>
          <button className="ptag" type="button" data-cat="rest">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M5 3v8a3 3 0 0 0 6 0V3M8 11v10M19 3c-1.7 1.2-2.5 3-2.5 5.5S17.3 13 19 14v7" />
            </svg>
            Restaurants
          </button>
          <button className="ptag" type="button" data-cat="fit">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M6.5 6.5v11M3.5 9v6M17.5 6.5v11M20.5 9v6M6.5 12h11" />
            </svg>
            Fitness
          </button>
          <button className="ptag" type="button" data-cat="saas">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="3" width="7" height="7" />
              <rect x="14" y="3" width="7" height="7" />
              <rect x="3" y="14" width="7" height="7" />
              <rect x="14" y="14" width="7" height="7" />
            </svg>
            SaaS
          </button>
          <button className="ptag" type="button" data-cat="estate">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 10.5 12 3l9 7.5" />
              <path d="M5 9.5V21h14V9.5" />
              <path d="M10 21v-6h4v6" />
            </svg>
            Real estate
          </button>
          <button className="ptag" type="button" data-cat="b2b">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="7" width="8" height="14" />
              <rect x="13" y="3" width="8" height="18" />
              <path d="M6 11h2M6 15h2M16 7h2M16 11h2M16 15h2" />
            </svg>
            B2B
          </button>
          <button className="ptag" type="button" data-cat="vibecoders">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="16 18 22 12 16 6" />
              <polyline points="8 6 2 12 8 18" />
            </svg>
            Vibecoders
          </button>
          <button className="ptag" type="button" data-cat="wtf">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 18.5v.01" />
              <path d="M9.2 8.7a2.9 2.9 0 1 1 4.3 2.6c-.9.5-1.5 1.2-1.5 2.2v.5" />
            </svg>
            WTF
          </button>
        </div> */}
      </div>
    </section>
  );
}

export default PromptSection;
