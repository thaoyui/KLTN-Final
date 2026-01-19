import React, { useEffect, useState } from 'react';
import { Shield, Filter, Clock, Server, User, AlertCircle, CheckCircle2, XCircle, X } from 'lucide-react';
import { benchmarkAPI } from '../services/benchmarkAPI';

interface AuditEvent {
    id?: number;
    type: string;
    action: string;
    command?: string;
    status: string;
    source?: string;
    nodeName?: string | null;
    clusterName?: string | null;
    checkId?: string | null;
    user?: string | null;
    timestamp?: string;
    details?: any;
}

const kubeVarMap: Record<string, string> = {
    '$apiserverconf': '/etc/kubernetes/manifests/kube-apiserver.yaml',
    '$apiserverbin': 'kube-apiserver',
    '$controllermanagerbin': 'kube-controller-manager',
    '$controllermanagerconf': '/etc/kubernetes/manifests/kube-controller-manager.yaml',
    '$schedulerbin': 'kube-scheduler',
    '$schedulerconf': '/etc/kubernetes/manifests/kube-scheduler.yaml',
    '$schedulerkubeconfig': '/etc/kubernetes/scheduler.conf',
    '$controllermanagerkubeconfig': '/etc/kubernetes/controller-manager.conf',
    '$etcddatadir': '/var/lib/etcd',
    '$etcdconf': '/etc/kubernetes/manifests/etcd.yaml',
    '$etcdbin': 'etcd',
    '$kubeletbin': 'kubelet',
    '$kubeletsvc': '/usr/lib/systemd/system/kubelet.service.d/10-kubeadm.conf',
    '$kubeletkubeconfig': '/etc/kubernetes/kubelet.conf',
    '$kubeletconf': '/var/lib/kubelet/config.yaml',
    '$kubeletcafile': '/etc/kubernetes/pki/ca.crt',
    '$proxybin': 'kube-proxy',
    '$proxykubeconfig': '/var/lib/kube-proxy/kubeconfig.conf',
    '$proxyconf': '/var/lib/kube-proxy/config.conf',
};

const applyKubeSubstitutions = (text?: string): string => {
    if (!text) return text || '';
    return Object.entries(kubeVarMap).reduce((acc, [key, value]) => acc.split(key).join(value), text);
};

const formatTime = (ts?: string) => {
    if (!ts) return 'Unknown';
    try {
        return new Date(ts).toLocaleString();
    } catch {
        return ts;
    }
};

const formatTypeLabel = (type: string) => {
    switch (type) {
        case 'bootstrap':
            return 'Bootstrap';
        case 'scan':
            return 'Scan';
        case 'remediation':
            return 'Remediation';
        case 'policy_generation':
            return 'Policy Generation';
        case 'mcp_bot':
            return 'Kubecheck Bot';
        default:
            return type || 'Other';
    }
};

const statusBadgeClass = (status: string) => {
    const s = status.toUpperCase();
    if (s === 'SUCCESS') {
        return 'bg-emerald-50 text-emerald-700 ring-emerald-100';
    }
    if (s === 'FAILED' || s === 'ERROR') {
        return 'bg-red-50 text-red-700 ring-red-100';
    }
    return 'bg-gray-50 text-gray-700 ring-gray-100';
};

const statusIcon = (status: string) => {
    const s = status.toUpperCase();
    if (s === 'SUCCESS') return <CheckCircle2 className="h-4 w-4 mr-1" />;
    if (s === 'FAILED' || s === 'ERROR') return <XCircle className="h-4 w-4 mr-1" />;
    return <AlertCircle className="h-4 w-4 mr-1" />;
};

export const AuditPage: React.FC = () => {
    const [events, setEvents] = useState<AuditEvent[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [typeFilter, setTypeFilter] = useState<string>('all');
    const [statusFilter, setStatusFilter] = useState<string>('all');
    const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);

    useEffect(() => {
        loadEvents();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const loadEvents = async () => {
        try {
            setLoading(true);
            setError(null);
            const params: { limit?: number; type?: string } = { limit: 100 };
            if (typeFilter !== 'all') {
                params.type = typeFilter;
            }
            const response = await benchmarkAPI.getAuditEvents(params);
            if (response.success && Array.isArray(response.data)) {
                setEvents(response.data);
            } else {
                setEvents([]);
            }
        } catch (e: any) {
            console.error('Failed to load audit events:', e);
            setError(e?.message || 'Failed to load audit events');
            setEvents([]);
        } finally {
            setLoading(false);
        }
    };

    const filteredEvents = events.filter((evt) => {
        if (statusFilter !== 'all' && evt.status && evt.status.toUpperCase() !== statusFilter.toUpperCase()) {
            return false;
        }
        return true;
    });

    return (
        <div className="p-8">
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-xl bg-blue-50 flex items-center justify-center">
                        <Shield className="h-6 w-6 text-blue-600" />
                    </div>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900">Audit Trail</h1>
                        <p className="text-sm text-gray-500">
                            Full history of bootstrap, scan, and remediation actions executed on your cluster.
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    <button
                        onClick={loadEvents}
                        className="px-3 py-2 text-sm font-medium text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100"
                    >
                        Refresh
                    </button>
                </div>
            </div>

            <div className="mb-4 flex flex-wrap items-center gap-3">
                <div className="flex items-center text-sm text-gray-500 gap-2">
                    <Filter className="h-4 w-4" />
                    <span>Filters</span>
                </div>
                <select
                    value={typeFilter}
                    onChange={(e) => setTypeFilter(e.target.value)}
                    className="text-sm rounded-md border-gray-300 focus:ring-blue-500 focus:border-blue-500"
                >
                    <option value="all">All types</option>
                    <option value="bootstrap">Bootstrap</option>
                    <option value="scan">Scan</option>
                    <option value="remediation">Remediation</option>
                </select>
                <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="text-sm rounded-md border-gray-300 focus:ring-blue-500 focus:border-blue-500"
                >
                    <option value="all">All statuses</option>
                    <option value="SUCCESS">Success only</option>
                    <option value="FAILED">Failed only</option>
                </select>
            </div>

            <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                {loading ? (
                    <div className="p-8 text-center text-gray-500">Loading audit events...</div>
                ) : error ? (
                    <div className="p-8 text-center text-red-500 text-sm">{error}</div>
                ) : filteredEvents.length === 0 ? (
                    <div className="p-12 text-center text-gray-500">
                        <p className="font-medium text-gray-900 mb-1">No audit events yet</p>
                        <p className="text-sm">Run a bootstrap, scan, or remediation to start building the audit history.</p>
                    </div>
                ) : (
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                            <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    When
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Type
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Action
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Target
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Status
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Actor
                                </th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {filteredEvents.map((evt, idx) => (
                                <tr
                                    key={evt.id || idx}
                                    className="hover:bg-gray-50 align-top cursor-pointer"
                                    onClick={() => setSelectedEvent(evt)}
                                >
                                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                                        <div className="flex items-center gap-1.5">
                                            <Clock className="h-4 w-4 text-gray-400" />
                                            {formatTime(evt.timestamp as string)}
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-700">
                                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                                            {formatTypeLabel(evt.type)}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-sm text-gray-900 max-w-md">
                                        <div className="font-medium">{evt.action}</div>
                                        {evt.command && (
                                            <div className="mt-1 text-xs text-gray-500 font-mono truncate">
                                                {evt.command}
                                            </div>
                                        )}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-gray-700">
                                        <div className="flex flex-col gap-0.5">
                                            {(evt.clusterName || evt.nodeName) && (
                                                <div className="flex items-center gap-1 text-xs text-gray-500">
                                                    <Server className="h-3 w-3" />
                                                    <span>{evt.clusterName || 'cluster'}{evt.nodeName ? ` · ${evt.nodeName}` : ''}</span>
                                                </div>
                                            )}
                                            {(evt.checkId || evt.details?.checkId) && (
                                                <div className="text-xs text-gray-500">
                                                    Check: <span className="font-mono">{evt.checkId || evt.details?.checkId}</span>
                                                </div>
                                            )}
                                            {evt.details && evt.details.resultSummary && (
                                                <div className="text-xs text-gray-500">
                                                    Results:{' '}
                                                    <span className="font-mono">
                                                        {`total=${evt.details.resultSummary.totalResults ?? evt.details.resultSummary.total ?? 0}, `}
                                                        {`passed=${evt.details.resultSummary.passed ?? evt.details.resultSummary.passedCount ?? 0}, `}
                                                        {`failed=${evt.details.resultSummary.failed ?? evt.details.resultSummary.failedCount ?? 0}`}
                                                    </span>
                                                </div>
                                            )}
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 whitespace-nowrap text-sm">
                                        <span
                                            className={
                                                'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ring-1 ' +
                                                statusBadgeClass(evt.status || '')
                                            }
                                        >
                                            {statusIcon(evt.status || '')}
                                            {evt.status || 'UNKNOWN'}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-700">
                                        <div className="flex items-center gap-1.5">
                                            <User className="h-4 w-4 text-gray-400" />
                                            <span>{evt.user || 'system'}</span>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {selectedEvent && (
                <div className="mt-6 bg-white rounded-xl shadow-sm border border-gray-200 overflow-x-hidden">
                    <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                        <div>
                            <p className="text-xs font-medium text-blue-600 uppercase tracking-wide">Audit Event</p>
                            <p className="text-lg font-semibold text-gray-900">{selectedEvent.action}</p>
                        </div>
                        <button
                            onClick={() => setSelectedEvent(null)}
                            className="text-gray-400 hover:text-gray-600"
                        >
                            <X className="h-5 w-5" />
                        </button>
                    </div>
                    <div className="px-6 py-4 space-y-4 overflow-x-hidden">
                        <div className="grid grid-cols-2 gap-4 text-sm">
                            <div>
                                <p className="text-xs font-medium text-gray-500 uppercase">When</p>
                                <p className="mt-0.5 text-gray-900">{formatTime(selectedEvent.timestamp)}</p>
                            </div>
                            <div>
                                <p className="text-xs font-medium text-gray-500 uppercase">Status</p>
                                <p className="mt-0.5">
                                    <span
                                        className={
                                            'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ring-1 ' +
                                            statusBadgeClass(selectedEvent.status || '')
                                        }
                                    >
                                        {statusIcon(selectedEvent.status || '')}
                                        {selectedEvent.status || 'UNKNOWN'}
                                    </span>
                                </p>
                            </div>
                            <div>
                                <p className="text-xs font-medium text-gray-500 uppercase">Type</p>
                                <p className="mt-0.5 text-gray-900">{formatTypeLabel(selectedEvent.type)}</p>
                            </div>
                            <div>
                                <p className="text-xs font-medium text-gray-500 uppercase">Actor</p>
                                <p className="mt-0.5 flex items-center gap-1.5 text-gray-900">
                                    <User className="h-4 w-4 text-gray-400" />
                                    {selectedEvent.user || 'system'}
                                </p>
                            </div>
                            {(selectedEvent.clusterName || selectedEvent.nodeName) && (
                                <div className="col-span-2">
                                    <p className="text-xs font-medium text-gray-500 uppercase">Target</p>
                                    <p className="mt-0.5 flex items-center gap-1.5 text-gray-900">
                                        <Server className="h-4 w-4 text-gray-400" />
                                        <span>
                                            {selectedEvent.clusterName || 'cluster'}
                                            {selectedEvent.nodeName ? ` · ${selectedEvent.nodeName}` : ''}
                                        </span>
                                    </p>
                                </div>
                            )}
                        </div>

                        <div className="border-t border-gray-200 pt-4">
                            <p className="text-xs font-medium text-gray-500 uppercase mb-1">Control-plane command</p>
                            <pre className="bg-gray-900 text-xs text-gray-100 rounded-md px-3 py-2 whitespace-pre-wrap break-all overflow-wrap-anywhere min-w-0 max-w-full overflow-hidden" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>
                                <code className="block break-all" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>{selectedEvent.command || 'N/A'}</code>
                            </pre>
                        </div>

                        <div>
                            <p className="text-xs font-medium text-gray-500 uppercase mb-1">Command executed on node</p>
                            <pre className="bg-gray-900 text-xs text-gray-100 rounded-md px-3 py-2 whitespace-pre-wrap break-all overflow-wrap-anywhere min-w-0 max-w-full overflow-hidden" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>
                                <code className="block break-all" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>{applyKubeSubstitutions(selectedEvent.details?.nodeCommand) || 'N/A'}</code>
                            </pre>
                        </div>

                        {selectedEvent.details?.shellCommands && Object.keys(selectedEvent.details.shellCommands).length > 0 && (
                            <div className="border-t border-gray-200 pt-4">
                                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Actual shell commands executed (scan)</p>
                                <div className="space-y-3">
                                    {Object.entries(selectedEvent.details.shellCommands).map(([checkId, commands]: [string, any]) => (
                                        <div key={checkId} className="bg-gray-50 rounded-md p-3 overflow-hidden">
                                            <p className="text-xs font-semibold text-gray-700 mb-1.5">Check {checkId}:</p>
                                            {Array.isArray(commands) ? (
                                                <ul className="space-y-1.5">
                                                    {commands.map((cmd: string, idx: number) => (
                                                        <li key={idx} className="overflow-hidden">
                                                            <pre className="bg-gray-900 text-xs text-gray-100 rounded px-2 py-1.5 whitespace-pre-wrap break-all overflow-wrap-anywhere min-w-0 max-w-full" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>
                                                                <code className="block break-all" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>{applyKubeSubstitutions(cmd)}</code>
                                                            </pre>
                                                        </li>
                                                    ))}
                                                </ul>
                                            ) : (
                                                <pre className="bg-gray-900 text-xs text-gray-100 rounded px-2 py-1.5 whitespace-pre-wrap break-all overflow-wrap-anywhere min-w-0 max-w-full" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>
                                                    <code className="block break-all" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>{applyKubeSubstitutions(String(commands))}</code>
                                                </pre>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {selectedEvent.details?.remediationShellCommand && (
                            <div className="border-t border-gray-200 pt-4">
                                <p className="text-xs font-medium text-gray-500 uppercase mb-1">Remediation shell command</p>
                                <pre className="bg-gray-900 text-xs text-gray-100 rounded-md px-3 py-2 whitespace-pre-wrap break-all overflow-wrap-anywhere min-w-0 max-w-full overflow-hidden" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>
                                    <code className="block break-all" style={{ wordBreak: 'break-all', overflowWrap: 'break-word' }}>{applyKubeSubstitutions(selectedEvent.details.remediationShellCommand)}</code>
                                </pre>
                            </div>
                        )}

                        {selectedEvent.details && (
                            <div className="border-t border-gray-200 pt-4">
                                <p className="text-xs font-medium text-gray-500 uppercase mb-1">Raw details</p>
                                <div className="overflow-x-auto">
                                    <pre className="bg-gray-50 text-xs text-gray-700 rounded-md px-3 py-2 whitespace-pre-wrap break-words overflow-wrap-anywhere max-h-96 overflow-y-auto min-w-0">
                                        <code className="block break-all">{JSON.stringify(selectedEvent.details, null, 2)}</code>
                                    </pre>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};


