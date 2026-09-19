import { useRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { Button } from '@/components/ui/button';

/** Native picker behind an accessible button; stored files are shown separately. */
export function FileUploadButton({
	onChange,
	disabled,
	icon,
	...props
}: InputHTMLAttributes<HTMLInputElement> & { icon?: ReactNode }) {
	const input = useRef<HTMLInputElement>(null);
	return (
		<>
			<input
				{...props}
				ref={input}
				type="file"
				hidden
				disabled={disabled}
				onChange={onChange}
			/>
			<Button
				type="button"
				variant="outline"
				size="sm"
				disabled={disabled}
				aria-label={props['aria-label'] || '选择文件'}
				onClick={() => input.current?.click()}
			>
				{icon}选择文件
			</Button>
		</>
	);
}
