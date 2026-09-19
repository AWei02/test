import { Loader2, CheckCircle, CircleAlert } from 'lucide-react';
import { useState, useEffect } from 'react';
import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from '@/components/ui/dialog';
import { useTranslation } from '@/i18n/useI18n';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	title: string;
	description?: ReactNode;
	confirmLabel?: string;
	onConfirm: () => Promise<void>;
}

export function DeleteDialog({
	open,
	onOpenChange,
	title,
	description,
	confirmLabel,
	onConfirm,
}: Props) {
	const { t } = useTranslation();
	const [deleting, setDeleting] = useState(false);
	const [error, setError] = useState('');
	useEffect(() => {
		if (open) setError('');
	}, [open]);

	const handleConfirm = async () => {
		setDeleting(true);
		setError('');
		try {
			await onConfirm();
			onOpenChange(false);
		} catch (e) {
			setError(e instanceof Error ? e.message : '删除失败');
		} finally {
			setDeleting(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-sm">
				<DialogHeader>
					<DialogTitle>{title}</DialogTitle>
					{description && <DialogDescription>{description}</DialogDescription>}
				</DialogHeader>
				<DialogFooter>
					{error && (
						<p role="alert" className="w-full text-sm text-destructive break-all">
							{error}
						</p>
					)}
					<Button variant="ghost" onClick={() => onOpenChange(false)} disabled={deleting}>
						<CircleAlert className="size-3.5" />
						{t('common.cancel')}
					</Button>
					<Button onClick={handleConfirm} disabled={deleting}>
						{deleting ? (
							<Loader2 className="size-3.5 animate-spin" />
						) : (
							<CheckCircle className="size-3.5" />
						)}
						{confirmLabel ?? t('common.confirm')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
