import { test, expect } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import App from './App';

test('renders Briefkasten AI header', () => {
  render(<App />);
  expect(screen.getByText(/Briefkasten AI/i)).toBeInTheDocument();
});
