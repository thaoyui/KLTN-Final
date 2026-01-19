const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:3001';

export interface BenchmarkSelection {
  id: string;
  timestamp: string;
  selectedItems: Array<{
    id: string;
    title: string;
    description: string;
    type: 'Automated' | 'Manual';
  }>;
  totalSelected: number;
  metadata?: any;
  status: string;
}

export interface ScanResult {
  id: string;
  selectionId: string;
  status: 'running' | 'completed' | 'failed';
  startTime: string;
  endTime?: string;
  progress: number;
  results: Array<{
    itemId: string;
    title: string;
    status: 'PASS' | 'FAIL';
    score: number;
    details: string;
    recommendations: string[];
    timestamp: string;
  }>;
}

class BenchmarkAPIService {
  private async makeRequest(endpoint: string, options: RequestInit = {}) {
    const url = `${API_BASE_URL}${endpoint}`;

    const defaultHeaders = {
      'Content-Type': 'application/json',
    };

    const config: RequestInit = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || data.error || 'API request failed');
      }

      return data;
    } catch (error) {
      console.error(`API Error (${endpoint}):`, error);
      throw error;
    }
  }

  // Submit benchmark selections
  async submitSelections(selectedItems: any[], metadata: any = {}) {
    return this.makeRequest('/api/selections', {
      method: 'POST',
      body: JSON.stringify({
        selectedItems,
        metadata: {
          source: 'frontend-dashboard',
          userAgent: navigator.userAgent,
          timestamp: new Date().toISOString(),
          ...metadata
        }
      }),
    });
  }

  // Get all selections
  async getSelections() {
    return this.makeRequest('/api/selections');
  }

  // Get specific selection
  async getSelection(selectionId: string) {
    return this.makeRequest(`/api/selections/${selectionId}`);
  }

  // Start benchmark scan
  async startScan(selectionId: string, config: any = {}, opts: { clusterName?: string; nodeName?: string } = {}) {
    return this.makeRequest('/api/scan', {
      method: 'POST',
      body: JSON.stringify({
        selectionId,
        clusterName: opts.clusterName,
        nodeName: opts.nodeName,
        config: {
          timeout: 300,
          parallel: false,
          ...config
        }
      }),
    });
  }

  // Get scan status and results
  async getScanStatus(scanId: string) {
    return this.makeRequest(`/api/scan/${scanId}`);
  }

  // Get all scans
  async getScans() {
    return this.makeRequest('/api/scans');
  }

  // Check API health
  async checkHealth() {
    return this.makeRequest('/health');
  }

  // Helper: Submit selections and start scan in one go
  async submitAndScan(
    selectedItems: any[],
    metadata: any = {},
    scanConfig: any = {},
    opts: { clusterName?: string; nodeName?: string } = {}
  ) {
    try {
      // 1. Submit selections
      const selectionResponse = await this.submitSelections(selectedItems, metadata);
      const selectionId = selectionResponse.data.selectionId;

      console.log('✅ Selections submitted:', selectionId);

      // 2. Start scan
      const scanResponse = await this.startScan(selectionId, scanConfig, opts);
      const scanId = scanResponse.data.scanId;

      console.log('🔍 Scan started:', scanId);

      return {
        selectionId,
        scanId,
        selection: selectionResponse.data,
        scan: scanResponse.data
      };
    } catch (error) {
      console.error('Error in submitAndScan:', error);
      throw error;
    }
  }

  // Helper: Poll scan status until completion
  async pollScanStatus(scanId: string, onProgress?: (progress: number, results: any[]) => void) {
    return new Promise((resolve, reject) => {
      const poll = async () => {
        try {
          const response = await this.getScanStatus(scanId);
          const scan = response.data;

          if (onProgress) {
            onProgress(scan.progress, scan.results);
          }

          if (scan.status === 'completed') {
            resolve(scan);
          } else if (scan.status === 'failed') {
            reject(new Error('Scan failed'));
          } else {
            // Continue polling
            setTimeout(poll, 2000); // Poll every 2 seconds
          }
        } catch (error) {
          reject(error);
        }
      };

      poll();
    });
  }

  // Generate HTML report from selected items
  async generateReport(selectedItems: any[], format: string = 'html', filename?: string) {
    return this.makeRequest('/api/generate-report', {
      method: 'POST',
      body: JSON.stringify({
        selectedItems,
        format,
        filename
      }),
    });
  }

  // Download report file
  async downloadReport(filename: string) {
    const url = `${API_BASE_URL}/api/download-report/${filename}`;

    try {
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`Download failed: ${response.statusText}`);
      }

      // Create blob and download
      const blob = await response.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);

      return { success: true };
    } catch (error) {
      console.error('Download error:', error);
      throw error;
    }
  }

  // Get audit events
  async getAuditEvents(params: { limit?: number; type?: string } = {}) {
    const query = new URLSearchParams();
    if (params.limit) query.append('limit', String(params.limit));
    if (params.type) query.append('type', params.type);

    const qs = query.toString();
    const endpoint = qs ? `/api/audit?${qs}` : '/api/audit';
    return this.makeRequest(endpoint);
  }

  // Export scan results to file
  async exportScanResults(scanResults: any[], format: string = 'html', filename?: string) {
    try {
      // Create export data
      const exportData = {
        scanResults,
        format,
        filename,
        timestamp: new Date().toISOString(),
        summary: {
          total: scanResults.length,
          passed: scanResults.filter((r: any) => r.status === 'PASS').length,
          failed: scanResults.filter((r: any) => r.status === 'FAIL').length,
          warnings: scanResults.filter((r: any) => r.status === 'WARN').length,
        }
      };

      if (format === 'json') {
        // Export as JSON
        const jsonStr = JSON.stringify(exportData, null, 2);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename || `scan-results-${Date.now()}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        return { success: true, message: 'Scan results exported as JSON' };
      } else if (format === 'pdf') {
        // Export as PDF
        const htmlContent = this.generateHTMLReport(exportData);
        await this.exportAsPDF(htmlContent, filename || `scan-results-${Date.now()}.pdf`);
        return { success: true, message: 'Scan results exported as PDF' };
      } else {
        // Export as HTML
        const htmlContent = this.generateHTMLReport(exportData);
        const blob = new Blob([htmlContent], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename || `scan-results-${Date.now()}.html`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        return { success: true, message: 'Scan results exported as HTML' };
      }
    } catch (error) {
      console.error('Error in exportScanResults:', error);
      throw error;
    }
  }

  // Export HTML content as PDF
  private async exportAsPDF(htmlContent: string, filename: string): Promise<void> {
    return new Promise(async (resolve, reject) => {
      try {
        // Load html2pdf.js from CDN if not already loaded
        if (!(window as any).html2pdf) {
          await new Promise<void>((scriptResolve, scriptReject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js';
            script.onload = () => scriptResolve();
            script.onerror = () => scriptReject(new Error('Failed to load html2pdf.js'));
            document.head.appendChild(script);
          });
        }

        const html2pdf = (window as any).html2pdf;
        
        // Create a temporary container for the HTML
        const element = document.createElement('div');
        element.innerHTML = htmlContent;
        element.style.position = 'absolute';
        element.style.left = '-9999px';
        document.body.appendChild(element);

        // Wait for images and content to load
        await new Promise(resolve => setTimeout(resolve, 500));

        const opt = {
          margin: [0.5, 0.5, 0.5, 0.5],
          filename: filename,
          image: { type: 'jpeg', quality: 0.98 },
          html2canvas: { 
            scale: 2,
            useCORS: true,
            logging: false
          },
          jsPDF: { 
            unit: 'in', 
            format: 'a4', 
            orientation: 'portrait' 
          }
        };

        await html2pdf().set(opt).from(element).save();
        document.body.removeChild(element);
        resolve();
      } catch (error) {
        // Fallback: Use browser print dialog
        try {
          const printWindow = window.open('', '_blank');
          if (!printWindow) {
            throw new Error('Failed to open print window. Please allow popups.');
          }

          printWindow.document.write(htmlContent);
          printWindow.document.close();

          await new Promise(resolve => setTimeout(resolve, 500));
          printWindow.print();
          
          setTimeout(() => {
            printWindow.close();
            resolve();
          }, 1000);
        } catch (fallbackError) {
          reject(fallbackError);
        }
      }
    });
  }

  // Helper function to parse check ID for sorting (e.g., "1.2.3" -> [1, 2, 3])
  private parseCheckId(checkId: string): number[] {
    if (!checkId) return [0];
    const parts = checkId.split('.').map(part => {
      const num = parseInt(part, 10);
      return isNaN(num) ? 0 : num;
    });
    return parts.length > 0 ? parts : [0];
  }

  // Sort checks by ID (ascending: 1.x.x before 5.x.x) - for reports
  private sortChecksByIdAscending(checks: any[]): any[] {
    return [...checks].sort((a, b) => {
      const idA = this.parseCheckId(a.itemId || a.id || '');
      const idB = this.parseCheckId(b.itemId || b.id || '');
      
      // Compare each part of the ID
      for (let i = 0; i < Math.max(idA.length, idB.length); i++) {
        const partA = idA[i] || 0;
        const partB = idB[i] || 0;
        if (partA !== partB) {
          return partA - partB; // Ascending order
        }
      }
      return 0;
    });
  }

  // Generate HTML report from scan results
  private generateHTMLReport(data: any): string {
    const { scanResults, summary, timestamp } = data;

    // Sort all items by ID (ascending: 1.x.x before 5.x.x) for report
    const sortedResults = this.sortChecksByIdAscending(scanResults);
    
    const passedItems = sortedResults.filter((r: any) => r.status === 'PASS');
    const failedItems = sortedResults.filter((r: any) => r.status === 'FAIL');
    const warningItems = sortedResults.filter((r: any) => r.status === 'WARN');

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kubernetes Security Scan Results</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #1f2937; margin-bottom: 10px; }
        .meta { color: #6b7280; margin-bottom: 30px; font-size: 14px; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .summary-card { padding: 20px; border-radius: 8px; text-align: center; }
        .summary-card.passed { background: #d1fae5; color: #065f46; }
        .summary-card.failed { background: #fee2e2; color: #991b1b; }
        .summary-card.warnings { background: #fef3c7; color: #92400e; }
        .summary-card.total { background: #e0e7ff; color: #3730a3; }
        .summary-number { font-size: 32px; font-weight: bold; margin-bottom: 5px; }
        .section { margin-top: 40px; }
        .section-title { font-size: 18px; font-weight: 600; margin-bottom: 15px; color: #1f2937; }
        .result-item { padding: 15px; margin-bottom: 10px; border-radius: 6px; border-left: 4px solid; }
        .result-item.pass { background: #f0fdf4; border-color: #22c55e; }
        .result-item.fail { background: #fef2f2; border-color: #ef4444; }
        .result-item.warn { background: #fffbeb; border-color: #f59e0b; }
        .result-id { font-weight: 600; color: #1f2937; }
        .result-title { color: #4b5563; margin-top: 5px; }
        .result-details { color: #6b7280; margin-top: 8px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Kubernetes Security Scan Results</h1>
        <div class="meta">Generated: ${new Date(timestamp).toLocaleString()}</div>
        
        <div class="summary">
            <div class="summary-card total">
                <div class="summary-number">${summary.total}</div>
                <div>Total Checks</div>
            </div>
            <div class="summary-card passed">
                <div class="summary-number">${summary.passed}</div>
                <div>Passed</div>
            </div>
            <div class="summary-card failed">
                <div class="summary-number">${summary.failed}</div>
                <div>Failed</div>
            </div>
            <div class="summary-card warnings">
                <div class="summary-number">${summary.warnings}</div>
                <div>Warnings</div>
            </div>
        </div>

        ${failedItems.length > 0 ? `
        <div class="section">
            <div class="section-title">Failed Checks (${failedItems.length})</div>
            ${failedItems.map((item: any) => `
                <div class="result-item fail">
                    <div class="result-id">${item.itemId || item.id}</div>
                    <div class="result-title">${item.title || ''}</div>
                    ${item.details ? `<div class="result-details">${item.details}</div>` : ''}
                </div>
            `).join('')}
        </div>
        ` : ''}

        ${warningItems.length > 0 ? `
        <div class="section">
            <div class="section-title">Warnings (${warningItems.length})</div>
            ${warningItems.map((item: any) => `
                <div class="result-item warn">
                    <div class="result-id">${item.itemId || item.id}</div>
                    <div class="result-title">${item.title || ''}</div>
                    ${item.details ? `<div class="result-details">${item.details}</div>` : ''}
                </div>
            `).join('')}
        </div>
        ` : ''}

        ${passedItems.length > 0 ? `
        <div class="section">
            <div class="section-title">Passed Checks (${passedItems.length})</div>
            ${passedItems.map((item: any) => `
                <div class="result-item pass">
                    <div class="result-id">${item.itemId || item.id}</div>
                    <div class="result-title">${item.title || ''}</div>
                </div>
            `).join('')}
        </div>
        ` : ''}
    </div>
</body>
</html>`;
  }

  // Generate and automatically download report (deprecated - use exportScanResults instead)
  async generateAndDownloadReport(selectedItems: any[], format: string = 'html', filename?: string) {
    try {
      // 1. Generate report
      const generateResponse = await this.generateReport(selectedItems, format, filename);

      if (!generateResponse.success) {
        throw new Error(generateResponse.message || 'Failed to generate report');
      }

      const reportFilename = generateResponse.data.filename;
      console.log('✅ Report generated:', reportFilename);

      // 2. Automatically download
      await this.downloadReport(reportFilename);

      return {
        success: true,
        filename: reportFilename,
        data: generateResponse.data
      };
    } catch (error) {
      console.error('Error in generateAndDownloadReport:', error);
      throw error;
    }
  }
  // Get scan history
  async getScanHistory(limit: number = 10) {
    return this.makeRequest(`/api/scans?limit=${limit}`, {
      method: 'GET',
    });
  }

  // Remediate specific checks
  async remediateCheck(checkIds: string[], opts: { clusterName?: string; nodeName?: string } = {}) {
    return this.makeRequest('/api/remediate', {
      method: 'POST',
      body: JSON.stringify({
        checkIds,
        clusterName: opts.clusterName,
        nodeName: opts.nodeName
      }),
    });
  }
}

export const benchmarkAPI = new BenchmarkAPIService();
export default benchmarkAPI;
