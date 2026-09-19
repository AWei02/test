import { createContext, useContext } from 'react';
import type { KnowledgeDocumentStatus } from '@/api';
import type { UploadTask } from './uploadTypes';

export interface UploadContextValue {
    tasks: UploadTask[];
    enqueue: (knowledgeBaseId: string, files: File[], permissions?: UploadTask['permissions'], parsing?: UploadTask['parsing']) => UploadTask[];
    cancel: (taskId: string) => void;
    dismiss: (taskId: string) => void;
    clearFinishedForKb: (knowledgeBaseId: string) => void;
    tasksForKb: (knowledgeBaseId: string) => UploadTask[];
    applyServerStatuses: (knowledgeBaseId: string, items: Array<{
        id: string; status: KnowledgeDocumentStatus; error: string | null;
    }>) => void;
    pollableDocumentIds: (knowledgeBaseId: string) => string[];
}

// Keep identity outside the React refresh boundary. Updating the provider must
// not create a different context from the one existing route consumers use.
export const UploadContext = createContext<UploadContextValue | null>(null);

export function useUploadContext(): UploadContextValue {
    const context = useContext(UploadContext);
    if (!context) throw new Error('useUploadContext must be used inside <UploadProvider>');
    return context;
}
