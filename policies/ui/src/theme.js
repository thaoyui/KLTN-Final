import { createTheme, rem } from '@mantine/core';

export const theme = createTheme({
    colors: {
        // Emerald / Teal for primary brand (Fresh, Security, Modern)
        brand: [
            '#e6fffa', // 0
            '#b2f5ea', // 1
            '#81e6d9', // 2
            '#4fd1c5', // 3
            '#38b2ac', // 4
            '#319795', // 5
            '#2c7a7b', // 6
            '#285e61', // 7
            '#234e52', // 8
            '#1d4044', // 9
        ],
        // Cool Gray / Slate for neutrals (Professional, Clean)
        slate: [
            '#f8fafc',
            '#f1f5f9',
            '#e2e8f0',
            '#cbd5e1',
            '#94a3b8',
            '#64748b',
            '#475569',
            '#334155',
            '#1e293b',
            '#0f172a',
        ],
    },
    primaryColor: 'brand',
    defaultRadius: 'md',
    fontFamily: 'Inter, sans-serif',
    headings: {
        fontFamily: 'Outfit, sans-serif',
    },
    components: {
        Paper: {
            defaultProps: {
                shadow: 'sm',
            },
        },
        Button: {
            defaultProps: {
                variant: 'filled',
            },
        },
    },
});
