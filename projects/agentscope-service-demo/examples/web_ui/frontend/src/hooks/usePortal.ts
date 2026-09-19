import { useQuery } from '@tanstack/react-query';
import { client } from '@/api/client';

export interface PortalUser {
	username: string;
	email: string;
	role: string;
	enabled: boolean;
	is_admin?: boolean;
}
export function usePortal() {
	const query = useQuery({
		queryKey: ['portal-me'],
		queryFn: () => client.get<PortalUser>('/portal/me', undefined, { silent: true, timeoutMs: 10000 }),
		retry: false,
	});
	return { ...query, isAdmin: query.data?.is_admin === true };
}
