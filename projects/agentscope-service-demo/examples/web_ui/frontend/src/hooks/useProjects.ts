import { useQuery } from '@tanstack/react-query';
import { client, getUserId } from '@/api/client';
export type Project = { id: string; name: string; description: string; owner: string; is_owner: boolean; agent_id?: string; shared?: boolean };
export type Binding = { agent_id: string; session_id: string; project_id: string; name?: string; created_at?: string };
export function useProjects() {
    return useQuery({ queryKey: ['projects', getUserId()], queryFn: () => client.get<{ projects: Project[]; bindings: Binding[] }>('/portal/projects'), retry: false, refetchInterval: 15000 });
}
