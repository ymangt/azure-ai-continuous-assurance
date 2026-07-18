import type { ReactNode } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
} from '@fluentui/react-components';
import { Open20Regular } from '@fluentui/react-icons';

interface OverviewPreviewDialogProps {
  open: boolean;
  title: string;
  bodyId: string;
  primaryLabel: string;
  children: ReactNode;
  onClose: () => void;
  onPrimary: () => void;
}

export function OverviewPreviewDialog({
  open,
  title,
  bodyId,
  primaryLabel,
  children,
  onClose,
  onPrimary,
}: OverviewPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(_, value) => { if (!value.open) onClose(); }}>
      <DialogSurface className="overview-preview-surface" aria-describedby={bodyId}>
        <DialogBody>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent className="dialog-content" id={bodyId}>
            {children}
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={onClose}>Stay on overview</Button>
            <Button appearance="primary" icon={<Open20Regular />} onClick={onPrimary}>{primaryLabel}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
