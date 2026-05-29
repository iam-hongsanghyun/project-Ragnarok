import React, { useState } from 'react';

export function SidebarGroup({
  title, icon, defaultOpen = false, badge, children,
}: {
  title: string;
  icon?: string;
  defaultOpen?: boolean;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="sg">
      <button className="sg-header" onClick={() => setOpen((o) => !o)}>
        {icon && <span className="sg-icon">{icon}</span>}
        <span className="sg-title">{title}</span>
        {badge}
        <span className={`sg-chevron${open ? ' is-open' : ''}`}>{open ? '-' : '+'}</span>
      </button>
      {open && <div className="sg-body">{children}</div>}
    </div>
  );
}
