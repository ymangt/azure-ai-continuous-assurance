import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Button, Text, Title2 } from '@fluentui/react-components';
import { Dismiss24Regular } from '@fluentui/react-icons';

interface DetailPanelProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  actions?: ReactNode;
}

export function DetailPanel({ title, subtitle, onClose, children, actions }: DetailPanelProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(document.activeElement instanceof HTMLElement ? document.activeElement : null);
  const [isOverlay, setIsOverlay] = useState(() => window.matchMedia('(max-width: 1050px)').matches);

  useEffect(() => {
    closeButtonRef.current?.focus();
    return () => {
      const opener = openerRef.current;
      window.requestAnimationFrame(() => { if (opener?.isConnected) opener.focus({ preventScroll: true }); });
    };
  }, []);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1050px)');
    const update = () => setIsOverlay(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    if (!isOverlay || !panelRef.current) return;
    const panel = panelRef.current;
    const background = [document.querySelector<HTMLElement>('.sidebar'), document.querySelector<HTMLElement>('.topbar')]
      .filter((element): element is HTMLElement => Boolean(element));
    const main = document.querySelector<HTMLElement>('#main-content');
    let branch: HTMLElement = panel;
    while (branch.parentElement) {
      const parent = branch.parentElement;
      [...parent.children].forEach((sibling) => {
        if (sibling !== branch && sibling instanceof HTMLElement && !sibling.classList.contains('detail-panel-scrim')) background.push(sibling);
      });
      if (parent === main) break;
      branch = parent;
    }
    const previous = background.map((element) => ({ element, inert: element.inert, ariaHidden: element.getAttribute('aria-hidden') }));
    background.forEach((element) => { element.inert = true; element.setAttribute('aria-hidden', 'true'); });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = [...panel.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
        .filter((element) => !element.hasAttribute('hidden'));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previous.forEach(({ element, inert, ariaHidden }) => {
        element.inert = inert;
        if (ariaHidden === null) element.removeAttribute('aria-hidden');
        else element.setAttribute('aria-hidden', ariaHidden);
      });
    };
  }, [isOverlay, onClose]);

  return (
    <Fragment>
      {isOverlay ? <button type="button" className="detail-panel-scrim" aria-label="Close details" onClick={onClose} /> : null}
      <aside ref={panelRef} className="detail-panel" role={isOverlay ? 'dialog' : undefined} aria-modal={isOverlay || undefined} aria-labelledby={titleId}>
        <div className="detail-panel-header">
          <div>
            <Title2 id={titleId} as="h2">{title}</Title2>
            {subtitle ? <Text className="muted">{subtitle}</Text> : null}
          </div>
          <Button ref={closeButtonRef} appearance="subtle" icon={<Dismiss24Regular />} aria-label="Close details" onClick={onClose} />
        </div>
        <div className="detail-panel-body">{children}</div>
        {actions ? <div className="detail-panel-actions">{actions}</div> : null}
      </aside>
    </Fragment>
  );
}
