import React, { useCallback, useRef, useState } from 'react';

const MIN_WIDTH = 180;
const MAX_WIDTH = 520;
const INITIAL_WIDTH = 252;

/** Sidebar open/collapse state plus drag-to-resize handling. Self-contained. */
export function useSidebarLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(INITIAL_WIDTH);
  const [isDraggingSidebar, setIsDraggingSidebar] = useState(false);
  const dragStartX = useRef<number>(0);
  const dragStartWidth = useRef<number>(INITIAL_WIDTH);

  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragStartX.current = e.clientX;
    dragStartWidth.current = sidebarWidth;
    setIsDraggingSidebar(true);

    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - dragStartX.current;
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, dragStartWidth.current + delta));
      setSidebarWidth(next);
    };
    const onUp = () => {
      setIsDraggingSidebar(false);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [sidebarWidth]);

  return { sidebarOpen, setSidebarOpen, sidebarWidth, isDraggingSidebar, handleResizeMouseDown };
}
