import { useQuery, useQueryClient } from '@tanstack/react-query';
import { client, getUserId } from '@/api/client';
import { portalWrite } from '@/api/portal';
export function useSessionPins() {
	const cache = useQueryClient();
	const key = ['session-pins', getUserId()];
	const query = useQuery({
		queryKey: key,
		queryFn: () =>
			client.get<{ agent_id: string; session_id: string }[]>('/portal/session-pins'),
	});
	const isPinned = (agent: string, session: string) =>
		!!query.data?.some((p) => p.agent_id === agent && p.session_id === session);
	const toggle = async (agent: string, session: string) => {
		await portalWrite('/portal/session-pins', 'POST', {
			agent_id: agent,
			session_id: session,
			pinned: !isPinned(agent, session),
		});
		await cache.invalidateQueries({ queryKey: key });
	};
	return { isPinned, toggle };
}
