import type { ReactNode } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Spinner,
  Text,
} from '@fluentui/react-components';

interface ActionDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  pending?: boolean;
  confirmDisabled?: boolean;
  destructive?: boolean;
  children?: ReactNode;
  onClose: () => void;
  onConfirm: () => void;
}

export function ActionDialog({ open, title, description, confirmLabel, pending = false, confirmDisabled = false, destructive = false, children, onClose, onConfirm }: ActionDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(_, data) => { if (!data.open && !pending) onClose(); }}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent className="dialog-content">
            <Text>{description}</Text>
            {children}
          </DialogContent>
          <DialogActions>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="secondary" disabled={pending} onClick={onClose}>Cancel</Button>
            </DialogTrigger>
            <Button appearance="primary" disabled={pending || confirmDisabled} onClick={onConfirm} className={destructive ? 'danger-button' : undefined}>
              {pending ? <><Spinner size="tiny" /> Working…</> : confirmLabel}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
