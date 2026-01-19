import React from 'react';
import { CheckCircle2, XCircle, AlertTriangle, X } from 'lucide-react';

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

const applyKubeSubstitutions = (text?: string) => {
    if (!text) return text;
    // Use split/join to stay compatible with older TS targets
    return Object.entries(kubeVarMap).reduce((acc, [key, value]) => acc.split(key).join(value), text);
};

interface ScanResultsModalProps {
    isOpen: boolean;
    onClose: () => void;
    results: any[];
}

export const ScanResultsModal: React.FC<ScanResultsModalProps> = ({
    isOpen,
    onClose,
    results,
}) => {
    if (!isOpen) return null;

    const passedCount = results.filter(r => r.status === 'PASS').length;
    // Count failed checks (excluding Manual checks which should be treated as warnings)
    const failedCount = results.filter(r => {
        if (r.status === 'FAIL') {
            const isManual = r.type === 'Manual' || 
                           (r.title && r.title.includes('(Manual)')) ||
                           (r.itemId && r.itemId.includes('Manual'));
            return !isManual; // Don't count Manual checks as failed
        }
        return false;
    }).length;
    // Count warnings: WARN status + Manual checks with FAIL status
    const warnCount = results.filter(r => {
        if (r.status === 'WARN') return true;
        if (r.status === 'FAIL') {
            const isManual = r.type === 'Manual' || 
                           (r.title && r.title.includes('(Manual)')) ||
                           (r.itemId && r.itemId.includes('Manual'));
            return isManual; // Count Manual FAIL checks as warnings
        }
        return false;
    }).length;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-50">
            <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] flex flex-col">
                {/* Header */}
                <div className="p-6 border-b border-gray-200 flex justify-between items-center">
                    <h2 className="text-xl font-semibold text-gray-900">Scan Results</h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
                        <X className="h-6 w-6" />
                    </button>
                </div>

                {/* Summary Stats */}
                <div className="bg-gray-50 px-6 py-4 border-b border-gray-200 flex space-x-8">
                    <div className="flex items-center">
                        <CheckCircle2 className="h-5 w-5 text-green-500 mr-2" />
                        <span className="font-medium text-gray-900">{passedCount} Passed</span>
                    </div>
                    <div className="flex items-center">
                        <XCircle className="h-5 w-5 text-red-500 mr-2" />
                        <span className="font-medium text-gray-900">{failedCount} Failed</span>
                    </div>
                    {warnCount > 0 && (
                        <div className="flex items-center">
                            <AlertTriangle className="h-5 w-5 text-yellow-500 mr-2" />
                            <span className="font-medium text-gray-900">{warnCount} Warnings</span>
                        </div>
                    )}
                </div>

                {/* Content */}
                <div className="p-6 overflow-y-auto flex-1">
                    {failedCount === 0 && warnCount === 0 ? (
                        <div className="text-center py-12">
                            <CheckCircle2 className="h-16 w-16 text-green-500 mx-auto mb-4" />
                            <h3 className="text-lg font-medium text-gray-900">All Checks Passed!</h3>
                            <p className="text-gray-500 mt-2">Your cluster configuration meets all selected benchmarks.</p>
                        </div>
                    ) : (
                        <div className="space-y-6">
                            {/* Failed Checks */}
                            {failedCount > 0 && (
                                <div>
                                    <h3 className="text-sm font-medium text-red-800 uppercase tracking-wider mb-3">Failed Checks</h3>
                                    <div className="space-y-3">
                                        {results.filter(r => {
                                            if (r.status === 'FAIL') {
                                                const isManual = r.type === 'Manual' || 
                                                               (r.title && r.title.includes('(Manual)')) ||
                                                               (r.itemId && r.itemId.includes('Manual'));
                                                return !isManual; // Only show non-Manual failed checks here
                                            }
                                            return false;
                                        }).map((result, idx) => {
                                            const remediationCommandRaw =
                                                result.command ||
                                                result.remediationCommand ||
                                                result.remediation_command ||
                                                result.fixCommand ||
                                                result.fix_command;

                                            const remediationCommand = applyKubeSubstitutions(remediationCommandRaw);
                                            const remediationText = applyKubeSubstitutions(result.remediation);

                                            const variables =
                                                result.variables ||
                                                result.metadata?.variables ||
                                                {};

                                            const variableEntries = Object.entries(variables);
                                            
                                            // Check if this is a Manual check (has "(Manual)" in title or type === 'Manual')
                                            const isManual = result.type === 'Manual' || 
                                                           (result.title && result.title.includes('(Manual)')) ||
                                                           (result.itemId && result.itemId.includes('Manual'));
                                            
                                            // Filter out "Check failed" text from details for Manual checks
                                            const displayDetails = isManual ? 'Manual verification required' : (result.details || '');

                                            return (
                                                <div key={idx} className={`${isManual ? 'bg-yellow-50 border-yellow-100' : 'bg-red-50 border-red-100'} border rounded-lg p-4`}>
                                                    <div className="flex items-start">
                                                        {isManual ? (
                                                            <AlertTriangle className="h-5 w-5 text-yellow-500 mt-0.5 mr-3 flex-shrink-0" />
                                                        ) : (
                                                            <XCircle className="h-5 w-5 text-red-500 mt-0.5 mr-3 flex-shrink-0" />
                                                        )}
                                                        <div className="space-y-3 w-full">
                                                            <div>
                                                                <h4 className={`text-sm font-medium ${isManual ? 'text-yellow-900' : 'text-red-900'}`}>
                                                                    {result.itemId}: {result.title}
                                                                </h4>
                                                                <p className={`text-sm mt-1 ${isManual ? 'text-yellow-700' : 'text-red-700'}`}>
                                                                    {displayDetails}
                                                                </p>
                                                            </div>

                                                            {variableEntries.length > 0 && (
                                                                <div className={`bg-white bg-opacity-60 rounded p-3 border ${isManual ? 'border-yellow-100' : 'border-red-100'}`}>
                                                                    <p className={`text-xs font-semibold mb-2 ${isManual ? 'text-yellow-800' : 'text-red-800'}`}>Variables</p>
                                                                    <div className="grid sm:grid-cols-2 gap-2">
                                                                        {variableEntries.map(([key, value]) => (
                                                                            <div key={key} className={`text-xs font-mono flex items-center justify-between ${isManual ? 'text-yellow-900' : 'text-red-900'}`}>
                                                                                <span className="mr-2">{key}</span>
                                                                                <span className={`px-2 py-1 rounded border ${isManual ? 'bg-yellow-100 text-yellow-800 border-yellow-200' : 'bg-red-100 text-red-800 border-red-200'}`}>
                                                                                    {String(value)}
                                                                                </span>
                                                                            </div>
                                                                        ))}
                                                                    </div>
                                                                </div>
                                                            )}

                                                            {remediationText && (
                                                                <div className={`bg-white bg-opacity-50 rounded p-2 text-xs font-mono border ${isManual ? 'text-yellow-800 border-yellow-100' : 'text-red-800 border-red-100'}`}>
                                                                    {remediationText}
                                                                </div>
                                                            )}

                                                            {remediationCommand && (
                                                                <div className={`bg-white bg-opacity-80 rounded p-3 border ${isManual ? 'border-yellow-100' : 'border-red-100'}`}>
                                                                    <p className={`text-xs font-semibold mb-2 ${isManual ? 'text-yellow-800' : 'text-red-800'}`}>Remediation Command</p>
                                                                    <div className={`text-xs font-mono rounded p-2 overflow-x-auto ${isManual ? 'text-yellow-900 bg-yellow-50 border border-yellow-100' : 'text-red-900 bg-red-50 border border-red-100'}`}>
                                                                        <code>{remediationCommand}</code>
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* Warnings */}
                            {warnCount > 0 && (
                                <div>
                                    <h3 className="text-sm font-medium text-yellow-800 uppercase tracking-wider mb-3">Warnings</h3>
                                    <div className="space-y-3">
                                        {results.filter(r => {
                                            if (r.status === 'WARN') return true;
                                            if (r.status === 'FAIL') {
                                                const isManual = r.type === 'Manual' || 
                                                               (r.title && r.title.includes('(Manual)')) ||
                                                               (r.itemId && r.itemId.includes('Manual'));
                                                return isManual; // Show Manual FAIL checks in Warnings section
                                            }
                                            return false;
                                        }).map((result, idx) => {
                                            // Check if this is a Manual check
                                            const isManual = result.type === 'Manual' || 
                                                           (result.title && result.title.includes('(Manual)')) ||
                                                           (result.itemId && result.itemId.includes('Manual'));
                                            
                                            // Filter out "Check failed" text from details for Manual checks
                                            const displayDetails = isManual ? 'Manual verification required' : (result.details || '');
                                            
                                            // Get remediation text and command for Manual checks
                                            const remediationCommandRaw =
                                                result.command ||
                                                result.remediationCommand ||
                                                result.remediation_command ||
                                                result.fixCommand ||
                                                result.fix_command;

                                            const remediationCommand = applyKubeSubstitutions(remediationCommandRaw);
                                            const remediationText = applyKubeSubstitutions(result.remediation);
                                            
                                            return (
                                                <div key={idx} className="bg-yellow-50 border border-yellow-100 rounded-lg p-4">
                                                    <div className="flex items-start">
                                                        <AlertTriangle className="h-5 w-5 text-yellow-500 mt-0.5 mr-3 flex-shrink-0" />
                                                        <div className="flex-1 space-y-3">
                                                            <div>
                                                                <h4 className="text-sm font-medium text-yellow-900">
                                                                    {result.itemId}: {result.title}
                                                                </h4>
                                                                <p className="text-sm text-yellow-700 mt-1">{displayDetails}</p>
                                                            </div>
                                                            
                                                            {/* Show remediation text for Manual checks */}
                                                            {remediationText && (
                                                                <div className="bg-white bg-opacity-50 rounded p-2 text-xs font-mono text-yellow-800 border border-yellow-100">
                                                                    <p className="text-xs font-semibold text-yellow-800 mb-1">Verification steps:</p>
                                                                    <pre className="text-xs text-yellow-700 whitespace-pre-wrap">{remediationText}</pre>
                                                                </div>
                                                            )}
                                                            
                                                            {/* Show remediation command if available */}
                                                            {remediationCommand && (
                                                                <div className="bg-white bg-opacity-80 rounded p-3 border border-yellow-100">
                                                                    <p className="text-xs font-semibold text-yellow-800 mb-2">Remediation Command:</p>
                                                                    <div className="text-xs font-mono text-yellow-900 bg-yellow-50 border border-yellow-100 rounded p-2 overflow-x-auto">
                                                                        <code>{remediationCommand}</code>
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="p-6 border-t border-gray-200 flex justify-end">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>
    );
};
