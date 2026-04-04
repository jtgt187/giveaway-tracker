import React from 'react';

// A safe, self-contained header with a complete inline SVG.
export default function BrandHeader() {
  return (
    <header style={headerStyle} aria-label="Brand Header" className="brand-header">
      <div style={logoWrapStyle} className="brand-logo" aria-label="Gleam logo" role="img">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="3" y="3" width="7" height="7" rx="1"/>
          <rect x="14" y="3" width="7" height="7" rx="1"/>
          <rect x="3" y="14" width="7" height="7" rx="1"/>
          <rect x="14" y="14" width="7" height="7" rx="1"/>
        </svg>
      </div>
      <div style={textWrapStyle}>
        <h1 style={titleStyle}>Giveaway Tracker</h1>
        <p style={subtitleStyle}>Discover, track, and auto-enter Gleam.io giveaways</p>
      </div>
    </header>
  );
}

// Lightweight inline styles (adjust or move to CSS as needed)
const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  padding: '12px 16px',
};
const logoWrapStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 28,
  height: 28,
};
const textWrapStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column' };
const titleStyle: React.CSSProperties = { margin: 0, fontSize: '1.25rem' };
const subtitleStyle: React.CSSProperties = { margin: 0, fontSize: '0.9rem', color: '#555' };
