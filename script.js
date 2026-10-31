'use strict';
/* ═══════════════════════════════════════════════════════════════════
   TEAM DEEP-X — CX Sentinel AI Presentation Script
   ═══════════════════════════════════════════════════════════════════ */

const LIFECYCLE_DETAILS = {
  1: {
    name: '01. Signal Intelligence',
    desc: 'Continuously ingests multi-channel signals in real-time across customer reviews, social posts, support tickets, and distributed system metrics. Preprocesses text using streaming NLP pipelines.'
  },
  2: {
    name: '02. Issue Detection & Clustering',
    desc: 'Applies HDBSCAN density clustering on semantic embeddings to group disparate complaints into single coherent issue incidents, eliminating duplicate alerts and surfacing true anomaly patterns.'
  },
  3: {
    name: '03. Customer Segmentation',
    desc: 'Isolates affected user cohorts by customer tier (Enterprise, VIP, SMB), client platform (Android, iOS, Web), and geographic region. Quantifies concentration to prioritize critical user bases first.'
  },
  4: {
    name: '04. Causal Root Cause Investigation',
    desc: 'Orchestrates hypothesis generation through LangGraph agents over a dynamic causal knowledge graph. Actively scores counter-evidence against logs and release events to prevent false blame.'
  },
  5: {
    name: '05. Business Impact Assessment',
    desc: 'Computes direct revenue at risk, churn probability curves, and projected refund liabilities. Equips leadership with financial justifications before any intervention is dispatched.'
  },
  6: {
    name: '06. Intervention Planning',
    desc: 'Ranks automated resolution options according to policy thresholds: logistics traffic rerouting, proactive service credits, targeted customer notifications, or canary deployment rollbacks.'
  },
  7: {
    name: '07. Human-Approved Execution [MANDATORY GATE]',
    desc: 'High-risk or financial recovery actions are routed to authorized managers (Approver role) via interactive review cards. Upon cryptographic approval, system executes idempotent enterprise API calls.'
  },
  8: {
    name: '08. Closed-Loop Telemetry Verification',
    desc: 'Monitors real-time operational telemetry and complaint velocity across a 24-48 hour observation window. Automatically reopens the incident and notifies responders if symptoms persist.'
  }
};

let currentSlide = 0;
const TOTAL_SLIDES = 5;

function goToSlide(n, dir = 'fwd') {
  if (n < 0 || n >= TOTAL_SLIDES || n === currentSlide) return;
  const slides = document.querySelectorAll('.slide');
  const from = slides[currentSlide];
  const to = slides[n];

  from.classList.remove('active');
  from.classList.add(dir === 'fwd' ? 'exit-l' : 'exit-r');
  setTimeout(() => from.classList.remove('exit-l', 'exit-r'), 500);

  to.style.cssText = `opacity:0;transform:translateX(${dir === 'fwd' ? 60 : -60}px) scale(.985);transition:none`;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    to.style.cssText = '';
    to.classList.add('active');
  }));

  currentSlide = n;
  syncNav();
  onSlideEnter(n);
}

function syncNav() {
  const prevBtn = document.getElementById('prev-btn');
  const nextBtn = document.getElementById('next-btn');
  const counter = document.getElementById('slide-counter');
  const progress = document.getElementById('progress-bar');

  if (prevBtn) prevBtn.disabled = currentSlide === 0;
  if (nextBtn) nextBtn.disabled = currentSlide === TOTAL_SLIDES - 1;
  if (counter) counter.textContent = `${currentSlide + 1} / ${TOTAL_SLIDES}`;
  if (progress) progress.style.width = `${((currentSlide + 1) / TOTAL_SLIDES) * 100}%`;

  document.querySelectorAll('.dot').forEach((d, i) => {
    d.classList.toggle('active', i === currentSlide);
  });
}

function onSlideEnter(n) {
  // Slide 3: animate cards sequentially
  if (n === 2) {
    document.querySelectorAll('.life-card').forEach((c, i) => {
      c.style.cssText = 'opacity:0;transform:translateY(12px);transition:none';
      setTimeout(() => {
        c.style.cssText = 'transition:opacity .3s ease,transform .3s ease';
        c.style.opacity = '1';
        c.style.transform = 'none';
      }, 50 + i * 50);
    });
  }

  // Slide 4: animate diff cards
  if (n === 3) {
    document.querySelectorAll('.diff-card').forEach((c, i) => {
      c.style.cssText = 'opacity:0;transform:translateY(14px);transition:none';
      setTimeout(() => {
        c.style.cssText = 'transition:opacity .35s ease,transform .35s ease';
        c.style.opacity = '1';
        c.style.transform = 'none';
      }, 60 + i * 60);
    });
  }

  // Slide 5: animate pillars
  if (n === 4) {
    document.querySelectorAll('.pillar-card').forEach((c, i) => {
      c.style.cssText = 'opacity:0;transform:translateY(14px);transition:none';
      setTimeout(() => {
        c.style.cssText = 'transition:opacity .35s ease,transform .35s ease';
        c.style.opacity = '1';
        c.style.transform = 'none';
      }, 70 + i * 80);
    });
  }
}

// Modal handling
function openModal(title, body) {
  const modal = document.getElementById('modal');
  const mTitle = document.getElementById('modal-title');
  const mBody = document.getElementById('modal-body');
  if (mTitle) mTitle.textContent = title;
  if (mBody) mBody.textContent = body;
  if (modal) modal.classList.add('open');
}

function closeModal() {
  const modal = document.getElementById('modal');
  if (modal) modal.classList.remove('open');
}

// Fullscreen
function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen();
  }
}

// Keyboard controls
document.addEventListener('keydown', e => {
  const modal = document.getElementById('modal');
  if (modal && modal.classList.contains('open')) {
    if (e.key === 'Escape') closeModal();
    return;
  }

  switch (e.key) {
    case 'ArrowRight':
    case 'ArrowDown':
    case ' ':
      e.preventDefault();
      goToSlide(currentSlide + 1, 'fwd');
      break;
    case 'ArrowLeft':
    case 'ArrowUp':
      e.preventDefault();
      goToSlide(currentSlide - 1, 'bwd');
      break;
    case 'f':
    case 'F':
      toggleFullscreen();
      break;
  }
});

// Init
document.addEventListener('DOMContentLoaded', () => {
  const firstSlide = document.querySelectorAll('.slide')[0];
  if (firstSlide) firstSlide.classList.add('active');
  syncNav();

  // Prev / Next buttons
  const prevBtn = document.getElementById('prev-btn');
  const nextBtn = document.getElementById('next-btn');
  if (prevBtn) prevBtn.addEventListener('click', () => goToSlide(currentSlide - 1, 'bwd'));
  if (nextBtn) nextBtn.addEventListener('click', () => goToSlide(currentSlide + 1, 'fwd'));

  // Dots
  document.querySelectorAll('.dot').forEach((d, i) => {
    d.addEventListener('click', () => goToSlide(i, i > currentSlide ? 'fwd' : 'bwd'));
  });

  // Fullscreen button
  const fsBtn = document.getElementById('fullscreen-btn');
  if (fsBtn) fsBtn.addEventListener('click', toggleFullscreen);

  // Modal close
  const closeBtn = document.getElementById('modal-close');
  const modal = document.getElementById('modal');
  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  if (modal) {
    modal.addEventListener('click', e => {
      if (e.target === modal) closeModal();
    });
  }

  // Lifecycle card click interaction (Slide 3)
  document.querySelectorAll('.life-card').forEach(card => {
    card.addEventListener('click', () => {
      const step = card.dataset.step;
      const detail = LIFECYCLE_DETAILS[step];
      if (detail) {
        openModal(detail.name, detail.desc);
      }
    });
  });
});

