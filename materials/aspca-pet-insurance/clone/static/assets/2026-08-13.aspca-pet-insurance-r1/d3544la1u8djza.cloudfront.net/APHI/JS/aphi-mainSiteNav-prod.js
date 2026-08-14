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

                document.querySelectorAll(".dropdownBtn").forEach(function (element) {
                    // Removes active class from dropdown button when the nav disappears
                    element.classList.remove("dropdownBtn--active");
                    // Resets aria-expanded value
                    element.setAttribute("aria-expanded", "false");
                });

                // Removes active class from dropdown list when the nav disappears
                document.querySelectorAll(".dropdownNav_list").forEach(function (element) {
                    element.classList.remove("dropdownNav_list--active");
                });
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

// Mobile Dropdown Toggles
//****************************************//
$(document).ready(function () {
    // Function to handle dropdown behavior
    function handleDropdown(btnId, dropdownId, backBtnId) {
        $(btnId).on('click', function () {
            $(dropdownId).toggleClass('dropdownNav_list--active');
            $(btnId).attr('aria-expanded', $(this).attr('aria-expanded') === 'true' ? 'false' : 'true');
            $(backBtnId).focus();

            if ($('.mobileDropdownItem').attr('tabindex') == -1) {
                $('.mobileDropdownItem').attr('tabindex', 0);
            } else {
                $('.mobileDropdownItem').attr('tabindex', -1);
            }
        });

        $(backBtnId).on('click', function () {
            $(dropdownId).toggleClass('dropdownNav_list--active');
            $(btnId).focus();

            if ($('.mobileDropdownItem').attr('tabindex') == 0) {
                $('.mobileDropdownItem').attr('tabindex', -1);
            } else {
                $('.mobileDropdownItem').attr('tabindex', 0);
            }
        });
    }

    // Call the function for each dropdown
    handleDropdown('#mobileDropdownBtn-petInsurance', '#mobileDropdown-petInsurance', '#petInsur-backBtn');
    handleDropdown('#mobileDropdownBtn-howItWorks', '#mobileDropdown-howItWorks', '#howItWorks-backBtn');
    handleDropdown('#mobileDropdownBtn-whyUs', '#mobileDropdown-whyUs', '#whyUs-backBtn');
    handleDropdown('#mobileDropdownBtn-resources', '#mobileDropdown-resources', '#resources-backBtn');
});

// Desktop Dropdown Toggles
//****************************************//
$(document).ready(function () {
    // Function to handle dropdown behavior
    function handleDropdown(btnId, dropdownId) {
        $(btnId).on('click', function () {
            $(btnId).toggleClass('dropdownBtn--active');
            $(dropdownId).toggleClass('dropdownNav_list--active');
            $(btnId).attr('aria-expanded', $(this).attr('aria-expanded') === 'true' ? 'false' : 'true');

            // Loop through other dropdowns and reset their state
            ['petInsurance', 'howItWorks', 'whyUs', 'resources'].forEach(function (dropdown) {
                if (btnId !== `#desktopDropdownBtn-${dropdown}`) {
                    $(`#desktopDropdownBtn-${dropdown}`).removeClass('dropdownBtn--active');
                    $(`#desktopDropdown-${dropdown}`).removeClass('dropdownNav_list--active');
                    $(`#desktopDropdownBtn-${dropdown}`).attr('aria-expanded', 'false');
                }
            });
        });
    }

    // Call the function for each dropdown
    handleDropdown('#desktopDropdownBtn-petInsurance', '#desktopDropdown-petInsurance');
    handleDropdown('#desktopDropdownBtn-howItWorks', '#desktopDropdown-howItWorks');
    handleDropdown('#desktopDropdownBtn-whyUs', '#desktopDropdown-whyUs');
    handleDropdown('#desktopDropdownBtn-resources', '#desktopDropdown-resources');
});