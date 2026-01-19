// Use relative path in production (via nginx proxy), absolute URL for local dev
const API_BASE_URL = process.env.REACT_APP_API_URL || '';

export interface InventoryNode {
    name: string;
    ip?: string;
    user?: string;
    role?: string;
    status?: string;
    note?: string;
}

class K8sAPIService {
    private async makeRequest(endpoint: string, options: RequestInit = {}) {
        const url = `${API_BASE_URL}${endpoint}`;
        const config: RequestInit = {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {}),
            },
        };

        const res = await fetch(url, config);
        const data = await res.json();
        if (!res.ok) {
            // Extract error from multiple possible locations
            const errorMsg = 
                data.error || 
                data.message || 
                data.details?.error ||
                data.details?.ssh_error ||
                (data.details?.output && data.details.output.includes('Permission denied') 
                    ? 'SSH Permission denied: The SSH key is not authorized on the remote node. Please add the public key to ~/.ssh/authorized_keys on the target node.'
                    : null) ||
                'API request failed';
            throw new Error(errorMsg);
        }
        return data;
    }

    async getInventory(clusterName = 'default', refresh = false) {
        const qs = new URLSearchParams({ clusterName });
        if (refresh) {
            qs.append('refresh', 'true');
        }
        return this.makeRequest(`/api/k8s/inventory?${qs.toString()}`);
    }

    async bootstrapNodes(clusterName: string, nodeNames: string[]) {
        // Validate input
        if (!nodeNames || nodeNames.length === 0) {
            throw new Error('At least one node name is required');
        }
        
        return this.makeRequest('/api/k8s/bootstrap', {
            method: 'POST',
            body: JSON.stringify({ 
                clusterName, 
                nodeNames: Array.isArray(nodeNames) ? nodeNames : [nodeNames]
            }),
        });
    }
}

export const k8sAPI = new K8sAPIService();
export default k8sAPI;


