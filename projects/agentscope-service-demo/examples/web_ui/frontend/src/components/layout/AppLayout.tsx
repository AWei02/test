import { Outlet, Navigate, useLocation } from "react-router-dom";
import { usePortal } from "@/hooks/usePortal";
import { ApiError } from "@/api/client";

import { AppSidebar } from "@/components/layout/AppSidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export function AppLayout() {
  const { isAdmin, isPending, error, refetch, isFetching } = usePortal();
  const location = useLocation();
  if (isPending) return <div className="p-10">正在加载工作台…</div>;
  if (
    error instanceof ApiError &&
    (error.status === 401 || error.status === 403)
  )
    return <Navigate to="/setup" replace />;
  if (error)
    return (
      <div className="p-10 space-y-4" role="alert">
        <h1 className="text-xl font-semibold">暂时无法连接工作台服务</h1>
        <p>服务器未响应或正在重启。这不是用户名或权限错误，请稍后重试。</p>
        <button
          className="rounded border px-4 py-2"
          disabled={isFetching}
          onClick={() => void refetch()}
        >
          {isFetching ? "正在重试…" : "重试连接"}
        </button>
      </div>
    );
  if (
    !isAdmin &&
    !location.pathname.startsWith("/chat") &&
    !location.pathname.startsWith("/projects") &&
    !location.pathname.startsWith("/schedule")
  )
    return <Navigate to="/chat" replace />;
  return (
    <div className="h-screen flex">
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset className="flex-1 overflow-hidden bg-canvas">
          <Outlet />
        </SidebarInset>
      </SidebarProvider>
    </div>
  );
}
