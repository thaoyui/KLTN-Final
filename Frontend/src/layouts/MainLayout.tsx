import React, { useEffect, useState } from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, Scan, Settings, Shield, ServerCog, PanelLeftClose, PanelLeftOpen, ShieldCheck, Bot } from 'lucide-react';
import { BootstrapModal, BootstrapNode } from '../components/BootstrapModal';
import { k8sAPI } from '../services/k8sAPI';

export const MainLayout: React.FC = () => {
    const location = useLocation();
    const [isBootstrapOpen, setIsBootstrapOpen] = useState(false);
    const [bootstrapNodes, setBootstrapNodes] = useState<BootstrapNode[]>([]);
    const [isLoadingNodes, setIsLoadingNodes] = useState(false);
    const [isBootstrapping, setIsBootstrapping] = useState(false);
    const [sidebarMessage, setSidebarMessage] = useState<string | null>(null);
    const [isCollapsed, setIsCollapsed] = useState(false);
    const clusterName = 'default';

    const isActive = (path: string) => location.pathname === path;

    useEffect(() => {
        if (isBootstrapOpen) {
            // Force refresh to ensure bootstrap status is up-to-date (even if remote files were removed)
            loadInventory(true);
        }
    }, [isBootstrapOpen]);

    const loadInventory = async (forceRefresh = false) => {
        try {
            setIsLoadingNodes(true);
            const res = await k8sAPI.getInventory(clusterName, forceRefresh);
            const nodes = (res.nodes || []).map((n: any) => ({
                name: n.name,
                role: n.role,
                status: (n.status as BootstrapNode['status']) || 'not_bootstrapped',
                note: n.note,
            }));
            setBootstrapNodes(nodes);
        } catch (err: any) {
            setSidebarMessage(err?.message || 'Failed to load inventory');
            setBootstrapNodes([]);
        } finally {
            setIsLoadingNodes(false);
        }
    };

    const handleBootstrap = async (selected: BootstrapNode[]) => {
        try {
            setIsBootstrapping(true);
            setSidebarMessage(null); // Clear previous messages
            const res = await k8sAPI.bootstrapNodes(clusterName, selected.map(n => n.name));
            if (res.success) {
                setSidebarMessage('Bootstrap completed successfully');
                // Refresh inventory with force refresh to bypass cache
                await loadInventory(true);
                // Notify other views (e.g., report dropdown) to refresh inventory
                window.dispatchEvent(new CustomEvent('inventory-updated'));
            } else {
                // Extract error from response (could be in error, details.error, or details.ssh_error)
                const errorMsg = res.error || res.details?.error || res.details?.ssh_error || 'Bootstrap failed';
                setSidebarMessage(errorMsg);
            }
        } catch (err: any) {
            // Error message is already extracted in k8sAPI.makeRequest
            setSidebarMessage(err?.message || 'Bootstrap failed');
        } finally {
            setIsBootstrapping(false);
        }
    };

    const sidebarWidth = isCollapsed ? '72px' : '256px';

    return (
        <div className="flex min-h-screen bg-gray-50">
            {/* Sidebar */}
            <div
                className="bg-white border-r border-gray-200 fixed h-full z-10 transition-all duration-200"
                style={{ width: sidebarWidth }}
            >
                <div className="p-4 border-b border-gray-200 flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                        <Shield className="h-8 w-8 text-indigo-600" />
                        {!isCollapsed && <span className="text-xl font-bold text-gray-900">KubeCheck</span>}
                    </div>
                    <button
                        onClick={() => setIsCollapsed(!isCollapsed)}
                        className="text-gray-500 hover:text-gray-700"
                        title={isCollapsed ? 'Expand' : 'Collapse'}
                    >
                        {isCollapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
                    </button>
                </div>
                <nav className="p-3 space-y-2">
                    <button
                        onClick={() => setIsBootstrapOpen(true)}
                        className={`w-full flex items-center ${isCollapsed ? 'justify-center' : 'space-x-3'} px-3 py-3 rounded-lg transition-colors text-white bg-indigo-600 hover:bg-indigo-700`}
                        title="Bootstrap Nodes"
                    >
                        <ServerCog className="h-5 w-5" />
                        {!isCollapsed && <span className="font-medium">Bootstrap Nodes</span>}
                    </button>
                    <Link
                        to="/"
                        className={`flex items-center ${isCollapsed ? 'justify-center' : 'space-x-3'} px-3 py-3 rounded-lg transition-colors ${isActive('/') ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50'
                            }`}
                        title="Dashboard"
                    >
                        <LayoutDashboard className="h-5 w-5" />
                        {!isCollapsed && <span className="font-medium">Dashboard</span>}
                    </Link>
                    <Link
                        to="/scan"
                        className={`flex items-center ${isCollapsed ? 'justify-center' : 'space-x-3'} px-3 py-3 rounded-lg transition-colors ${isActive('/scan') ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50'
                            }`}
                        title="Scan & Fix"
                    >
                        <Scan className="h-5 w-5" />
                        {!isCollapsed && <span className="font-medium">Scan & Fix</span>}
                    </Link>
                    <Link
                        to="/audit"
                        className={`flex items-center ${isCollapsed ? 'justify-center' : 'space-x-3'} px-3 py-3 rounded-lg transition-colors ${isActive('/audit') ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50'
                            }`}
                        title="Audit Trail"
                    >
                        <ShieldCheck className="h-5 w-5" />
                        {!isCollapsed && <span className="font-medium">Audit Trail</span>}
                    </Link>
                    <Link
                        to="/mcp-bot"
                        className={`flex items-center ${isCollapsed ? 'justify-center' : 'space-x-3'} px-3 py-3 rounded-lg transition-colors ${isActive('/mcp-bot') ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50'
                            }`}
                        title="Kubecheck Bot"
                    >
                        <Bot className="h-5 w-5" />
                        {!isCollapsed && <span className="font-medium">Kubecheck Bot</span>}
                    </Link>
                    <Link
                        to="/settings"
                        className={`flex items-center ${isCollapsed ? 'justify-center' : 'space-x-3'} px-3 py-3 rounded-lg transition-colors ${isActive('/settings') ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50'
                            }`}
                        title="Settings"
                    >
                        <Settings className="h-5 w-5" />
                        {!isCollapsed && <span className="font-medium">Settings</span>}
                    </Link>
                    {sidebarMessage && !isCollapsed && (
                        <p className="mt-2 text-xs text-blue-700 bg-blue-50 border border-blue-100 rounded px-3 py-2">
                            {sidebarMessage}
                        </p>
                    )}
                </nav>
            </div>

            {/* Main Content */}
            <div className="flex-1" style={{ marginLeft: sidebarWidth }}>
                <Outlet />
            </div>

            <BootstrapModal
                isOpen={isBootstrapOpen}
                onClose={() => setIsBootstrapOpen(false)}
                nodes={bootstrapNodes}
                onBootstrap={handleBootstrap}
                isLoading={isBootstrapping || isLoadingNodes}
            />
        </div>
    );
};
