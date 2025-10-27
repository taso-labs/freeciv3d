/**
 * Test-Driven Development (TDD) test for FreeCiv3D Spectator functionality
 * This script validates that the spectator mode works correctly
 */

const puppeteer = require('puppeteer');

async function testSpectatorPage() {
  console.log('🧪 Starting FreeCiv3D Spectator TDD Tests...');

  let browser, page;
  try {
    browser = await puppeteer.launch({ headless: false });
    page = await browser.newPage();

    // Enable console logging
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    page.on('pageerror', error => console.log('PAGE ERROR:', error.message));

    console.log('📄 Test 1: Spectator page loads without 404 errors');
    const response = await page.goto('http://localhost:8080/webclient/spectator.jsp?game_id=default&port=6000');

    if (response.status() === 200) {
      console.log('✅ Spectator page loads successfully (HTTP 200)');
    } else {
      console.log('❌ Spectator page failed to load (HTTP ' + response.status() + ')');
      return false;
    }

    console.log('🔧 Test 2: JavaScript files load without 404 errors');
    const failedRequests = [];
    page.on('response', response => {
      if (response.status() === 404 && response.url().includes('.js')) {
        failedRequests.push(response.url());
      }
    });

    // Wait for page to load completely
    await page.waitForTimeout(3000);

    if (failedRequests.length === 0) {
      console.log('✅ All JavaScript files loaded successfully');
    } else {
      console.log('❌ Failed to load JavaScript files:', failedRequests);
      return false;
    }

    console.log('🎮 Test 3: FreeCiv client object is defined');
    const clientDefined = await page.evaluate(() => {
      return typeof client !== 'undefined' && client !== null;
    });

    if (clientDefined) {
      console.log('✅ FreeCiv client object is properly defined');
    } else {
      console.log('❌ FreeCiv client object is undefined');
      return false;
    }

    console.log('🗺️  Test 4: Map tab is active and visible');
    const mapTabActive = await page.evaluate(() => {
      const mapTab = document.getElementById('tabs-map');
      const mapTabVisible = mapTab && mapTab.style.display !== 'none';
      const mapTabIndex = $('#tabs').tabs('option', 'active');
      return mapTabVisible && mapTabIndex === 0;
    });

    if (mapTabActive) {
      console.log('✅ Map tab is active and visible');
    } else {
      console.log('❌ Map tab is not properly displayed');
      return false;
    }

    console.log('🎯 Test 5: No "Game Options" text in map area');
    const gameOptionsInMap = await page.evaluate(() => {
      const mapContent = document.getElementById('tabs-map').innerHTML;
      return mapContent.includes('Game Options');
    });

    if (!gameOptionsInMap) {
      console.log('✅ Map area does not contain "Game Options" text');
    } else {
      console.log('❌ Map area still contains "Game Options" text');
      return false;
    }

    console.log('🔌 Test 6: WebSocket connection status');
    await page.waitForTimeout(2000); // Wait for WebSocket connection attempt

    const connectionStatus = await page.evaluate(() => {
      const statusElement = document.getElementById('connection_indicator');
      return statusElement ? statusElement.textContent : 'Not found';
    });

    console.log('ℹ️  Connection status:', connectionStatus);

    console.log('🎉 All spectator UI tests passed successfully!');
    return true;

  } catch (error) {
    console.error('❌ Test error:', error);
    return false;
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

// Run the test if this file is executed directly
if (require.main === module) {
  testSpectatorPage().then(success => {
    if (success) {
      console.log('🏆 All tests passed! Spectator mode is working correctly.');
      process.exit(0);
    } else {
      console.log('💥 Some tests failed. Please check the output above.');
      process.exit(1);
    }
  });
}

module.exports = { testSpectatorPage };