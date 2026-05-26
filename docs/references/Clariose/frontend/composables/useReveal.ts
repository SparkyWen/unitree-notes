/**
 * useReveal — minimal reveal-on-scroll using IntersectionObserver.
 * Adds `is-visible` to any element with `data-reveal` once it enters
 * the viewport. CSS handles the actual fade/translate transition.
 */
export function useReveal() {
  if (import.meta.server) return;

  onMounted(() => {
    const els = Array.from(document.querySelectorAll<HTMLElement>('[data-reveal]'));
    if (!('IntersectionObserver' in window)) {
      els.forEach(el => el.classList.add('is-visible'));
      return;
    }
    const io = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            io.unobserve(entry.target);
          }
        }
      },
      { rootMargin: '0px 0px -10% 0px', threshold: 0.05 },
    );
    els.forEach(el => io.observe(el));
  });
}
