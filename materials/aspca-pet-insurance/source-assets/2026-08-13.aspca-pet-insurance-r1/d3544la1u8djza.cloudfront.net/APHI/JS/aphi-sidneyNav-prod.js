// Make nav disappear and appear on scroll up
//****************************************//
function checkPageOffset(x) {
    if (x.matches) { // If desktop
        var prevScrollpos = window.pageYOffset;
        window.onscroll = () => {
            let currentScrollpos = window.pageYOffset;
            if (prevScrollpos > currentScrollpos || currentScrollpos <= 1080) {
                document.getElementById('desktopHeaderContainer').style.top = "0";
            } else {
                document.getElementById('desktopHeaderContainer').style.top = "-128px";
            }
            prevScrollpos = currentScrollpos;
        };
    } else { // If mobile
        var prevScrollpos = window.pageYOffset;
        window.onscroll = () => {
            let currentScrollpos = window.pageYOffset;
            if (prevScrollpos > currentScrollpos || currentScrollpos <= 68) {
                document.getElementById('mobileHeader').style.top = "0";
            } else {
                document.getElementById('mobileHeader').style.top = "-68px";
            }
            prevScrollpos = currentScrollpos;
        };
    }
};

var x = window.matchMedia("(min-width: 1160px)"); // Set to desktop breakpoint
checkPageOffset(x); // Call listener function at run time
x.addListener(scroll); // Attach listener function on state changes 

// Hamburger Toggle
//****************************************//
$(document).ready(function () {
    $(function () {
        // toggle slide animation when clicking on the mobile menu button
        $('#menuToggle').click(function () {
            $('#mobileNavContainer').slideToggle(300);
        });
        // add class "active" when clicking on the mobile menu button
        $('#menuToggle').on('click', function () {
            $("body").toggleClass("over");
            $(".hamburger").toggleClass("animate");
            $(".header--mobile").toggleClass("mobileHeaderContainer");
            $('#menuToggle').attr('aria-expanded', $(this).attr('aria-expanded') === 'true' ? 'false' : 'true');
            $('#mobileFreeQuoteBtn').toggleClass('d_block');
        });
    }); // end DOM ready
});

// If click on link in Sidney
//****************************************//
$(document).ready(function () {
    $('#mobileDropdownBtn-fetchQuote, #mobileDropdownBtn-startNewQuote').on('click', function () {
        // toggle slide animation when clicking on the fetch quote nav item
        $('#mobileNavContainer').slideToggle(300);

        // add class "active" when clicking on the mobile menu button
        $("body").toggleClass("over");
        $(".hamburger").toggleClass("animate");
        $(".header--mobile").toggleClass("mobileHeaderContainer");
        $('#menuToggle').attr('aria-expanded', 'false');

        if ($(this).attr('id') === 'mobileDropdownBtn-fetchQuote') {
            // Focus heading when mobile menu closes and we are directed to the RTQ screen
            $('#welcomeBackHeading').focus();
        }
    });
});