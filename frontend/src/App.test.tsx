import { test, expect } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import App from './App';

test('renders Briefkasten AI header', () => {
  render(<App />);
  expect(screen.getAllByText(/Briefkasten AI/i).length).toBeGreaterThan(0);
});
