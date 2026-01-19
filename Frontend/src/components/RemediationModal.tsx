import React from 'react';
import { Loader2, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

type CheckDetail = {
    checkId: string;
    remediation?: string;
};

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
    return Object.entries(kubeVarMap).reduce((acc, [key, value]) => acc.split(key).join(value), text);
};

interface RemediationModalProps {
    isOpen: boolean;
    onClose: () => void;
    onConfirm: () => void;
    checkIds: string[];
    checkDetails?: CheckDetail[];
    isLoading: boolean;
    results: any[] | null;
}

export const RemediationModal: React.FC<RemediationModalProps> = ({
    isOpen,
    onClose,
    onConfirm,
    checkIds,
    isLoading,
    results,
    checkDetails = [],
}) => {
    if (!isOpen) return null;

    const detailsMap = checkDetails.reduce<Record<string, string | undefined>>((acc, cur) => {
        acc[cur.checkId] = applyKubeSubstitutions(cur.remediation);
        return acc;
    }, {});

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-50">
            <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] flex flex-col">
                {/* Header */}
                <div className="p-6 border-b border-gray-200">
                    <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                        <AlertTriangle className="h-6 w-6 text-yellow-500 mr-2" />
                        {results ? 'Remediation Results' : `Confirm Remediation (${checkIds.length} checks)`}
                    </h2>
                </div>

                {/* Content */}
                <div className="p-6 overflow-y-auto flex-1">
                    {!results ? (
                        <>
                            <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 mb-6">
                                <div className="flex">
                                    <div className="ml-3">
                                        <p className="text-sm text-yellow-700">
                                            You are about to execute remediation commands on your cluster.
                                            This action involves running privileged commands (sudo) and may modify system configurations.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            <p className="mb-4 text-gray-700 font-medium">
                                The following checks will be remediated:
                            </p>
                            <div className="bg-gray-100 rounded-md p-4 max-h-80 overflow-y-auto space-y-3">
                                {checkIds.map(id => (
                                    <div key={id} className="bg-white rounded border border-gray-200 p-3 shadow-sm">
                                        <p className="text-sm font-semibold text-gray-900">{id}</p>
                                        {detailsMap[id] && (
                                            <div className="mt-2 bg-red-50 border border-red-100 rounded p-2">
                                                <p className="text-xs font-semibold text-red-800 mb-1">Remediation command(s)</p>
                                                <pre className="text-xs text-red-800 whitespace-pre-wrap font-mono">
                                                    {detailsMap[id]}
                                                </pre>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>

                            <div className="mt-6 flex justify-end space-x-3">
                                <button
                                    onClick={onClose}
                                    className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                                >
                                    No, Cancel
                                </button>
                                <button
                                    onClick={onConfirm}
                                    disabled={isLoading}
                                    className="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-red-600 hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 flex items-center"
                                >
                                    {isLoading && <Loader2 className="animate-spin -ml-1 mr-2 h-4 w-4" />}
                                    Yes, Fix Issues
                                </button>
                            </div>
                        </>
                    ) : (
                        <div className="space-y-4">
                            <div className="flex items-center justify-between mb-4">
                                <span className="font-medium text-gray-700">Execution Summary:</span>
                                <div className="flex space-x-4 text-sm">
                                    <span className="text-green-600 flex items-center">
                                        <CheckCircle2 className="h-4 w-4 mr-1" />
                                        {results.filter(r => r.success).length} Success
                                    </span>
                                    <span className="text-red-600 flex items-center">
                                        <XCircle className="h-4 w-4 mr-1" />
                                        {results.filter(r => !r.success).length} Failed
                                    </span>
                                </div>
                            </div>

                            <div className="border rounded-md divide-y">
                                {results.map((result, idx) => (
                                    <div key={idx} className="p-3 flex items-start justify-between hover:bg-gray-50">
                                        <div className="flex-1">
                                            <div className="flex items-center">
                                                {result.success ? (
                                                    <CheckCircle2 className="h-5 w-5 text-green-500 mr-2" />
                                                ) : (
                                                    <XCircle className="h-5 w-5 text-red-500 mr-2" />
                                                )}
                                                <span className="font-medium text-gray-900">{result.checkId}</span>
                                                {/* Verification Tag */}
                                                {result.action === 'verify' && (
                                                    <span className={`ml-2 px-2 py-0.5 text-xs rounded-full font-medium ${result.status === 'PASS'
                                                        ? 'bg-green-100 text-green-800'
                                                        : 'bg-yellow-100 text-yellow-800'
                                                        }`}>
                                                        {result.status === 'PASS' ? 'Verified Fixed' : 'Fix Applied - Verification Failed'}
                                                    </span>
                                                )}
                                            </div>

                                            {/* Messages */}
                                            {result.message && (
                                                <p className={`mt-1 text-sm ml-7 ${result.success ? 'text-gray-600' : 'text-red-600'}`}>
                                                    {result.message}
                                                </p>
                                            )}

                                            {/* Error Details */}
                                            {!result.success && result.error && (
                                                <p className="mt-1 text-sm text-red-600 ml-7">
                                                    {result.error}
                                                </p>
                                            )}

                                            {/* Command Info */}
                                            {result.details?.remediation_result?.command && (
                                                <div className="mt-1 ml-7">
                                                    <p className="text-xs text-cool-gray-500 font-mono bg-gray-50 p-1 rounded inline-block">
                                                        {`> ${result.details.remediation_result.command}`}
                                                    </p>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer for Results View */}
                {results && (
                    <div className="p-6 border-t border-gray-200 flex justify-end">
                        <button
                            onClick={onClose}
                            className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                        >
                            Close
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
};
